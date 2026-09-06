# Phase 9 Opportunity Scoring V1 — Design sources

This slice is a pure deterministic transform with no external provider, so there
is no provider API to cite. The design basis and the requirements it implements
are recorded here for auditability; verified on 2026-07-24.

## Requirement basis

- Onyx PRD, Phase 9 "Intelligence and opportunity radar", item 3: transparent
  opportunity scoring for pain/economic cost, urgency, buyer/payability, timing,
  competition, Cyryx advantage, time to MVP/revenue, complexity, distribution,
  moat, legal/platform risk and evidence confidence
  (`plans/onyx-advanced-entity-redesign.md`).
- Phase 9 verification guards: scoring must be transparent, and geopolitical or
  financial signals must never become autonomous trading actions.

## Scoring model

- The twelve PRD dimensions are modelled explicitly. Eight are benefit
  dimensions (a higher raw score means a better opportunity) and four are
  cost/risk dimensions — competition, time to MVP/revenue, complexity and
  legal/platform risk — whose effective value is inverted (`SCORE_MAX - raw`) so
  a lower raw risk scores higher. This mirrors standard weighted opportunity /
  ICE-style scoring, but with fixed, published integer weights rather than
  learned or model-assigned ones so every total is auditable and reproducible.
- Normalisation uses deterministic integer half-up rounding to a `0..100` total,
  and a fixed band ladder (`watch`/`consider`/`pursue`/`priority`). Evidence
  confidence contributes as a weighted benefit dimension and additionally raises
  an explicit `low_confidence` flag at or below its floor.

## Transparency and safety

- Each result carries the full per-dimension breakdown (raw, direction,
  effective value, weight, earned points, maximum points), so the total can be
  recomputed from the record without the module.
- The module has no network, model, persistence or action primitive; a score is
  advisory data only. It cannot, by construction, turn any signal into a trade
  or other side effect.

## Deliberately out of scope

- Live/primary source ingestion, model-assisted or learned weighting,
  opportunity clustering, and any autonomous acting on a score — each a later
  gated successor. World Monitor remains `BLOCKED_BY_LICENSE`.
