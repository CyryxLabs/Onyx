# Phase 10 audience/strategy V1 checkpoint

Fifth Phase 10 (social organic OS) slice: a default-off, deterministic,
hermetic audience-research and strategy contract. It adds one module, one
feature flag and no runtime wiring.

`core/phase10_audience_strategy_v1.py`
(`ONYX_PHASE10_AUDIENCE_STRATEGY_V1`) is entry-bound to the accepted Phase
10 content-draft four-file acceptance tuple. It builds cited
`ResearchClaimV1`/`AudienceSegmentV1` records (source_ref required; ≥1 claim
per segment), per-platform `KpiV1` records (horizon ∈ 30/60/90;
cross-platform equivalence unrepresentable), ordered `FunnelStageV1` records
referencing known KPIs, `StrategyPlanV1` records with exactly the 30/60/90
horizons, and sample-floored `ExperimentV1` records (min_sample ≥ 100;
winner requires observed ≥ min) into a sealed snapshot with projections
only. No publish/schedule/action surface. The module calls no model, opens
no network, spawns no process, persists nothing and takes no action.

The cumulative selection reproduces 833 passing tests and 96 passing
subtests across thirty-two fresh Python processes — the thirty-one files of
the Guild A9.4 selection plus this slice's thirty-seven adversarial tests —
with seventeen platform-specific skips and zero failure/error.

Scope and limits: strategy substrate only. No publishing/scheduling, no
live provider reads (BLOCKED_BY_ACCESS), no analytics ingestion, no paid
media, no startup/voice/UI/dashboard wiring, and no claim that the full
Onyx PRD is complete.
