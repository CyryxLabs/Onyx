# Phase 10 audience/strategy V1 — sources and design basis

Hermetic, deterministic strategy contract. No external service is used; the
basis is the governing PRD strategy requirements and the platform-policy
principles the gates encode.

## PRD basis

- Phase 10 strategy items: audience/trend research, 30/60/90 strategy,
  funnel/KPI, experiment ledger (deterministic, buildable now — plan item
  A20 in `CAPABILITY_COMPLETION_PLAN_90PCT.md`).
- Phase 10 guards: never fabricate research/testimonials/stats; no
  cross-platform metric equivalence; no experiment-winner claims from
  inadequate samples.

## Design decisions (each guard encoded as an invariant)

- **Cited research** — `source_ref` required per claim; ≥1 claim per
  segment; audiences cannot be invented.
- **Per-platform metrics** — a KPI names exactly one slice-1 platform;
  cross-platform equivalence is unrepresentable.
- **30/60/90 as key-set** — `goals_30/60/90` exactly, each non-empty.
- **Sample floor** — `min_sample ≥ 100`; winner requires
  `observed ≥ min_sample`, structurally.
- **Entry-bound** to the accepted slice-4 tuple; reproduction through the
  current-successor chain established 2026-08-17.
