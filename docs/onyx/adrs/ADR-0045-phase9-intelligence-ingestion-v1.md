# ADR-0045 — Phase 9 intelligence ingestion V1

## Status

Proposed (candidate E1–E5 complete, E6 pending).

## Context

Phase 9 of the Onyx PRD adds an intelligence and opportunity radar. Its second
"what to implement" item requires that ingested items record publication time
and event time separately, that recycled stories be deduplicated, that each
claim be separated into fact / inference / scenario / recommendation, and that
consequential claims be corroborated where possible. The PRD's verification
guards require citation correctness, temporal freshness, source health and
duplicate-story evaluations to pass, and prohibit turning geopolitical or
financial headlines into autonomous trading actions.

This is the first Phase 9 slice. It must be additive, exactly default-off, and —
because the radar consumes external intelligence — must not itself fetch any
source, call any model, persist anything, or take any action.

## Decision

Add a pure deterministic, default-off `phase9-intelligence-ingestion-v1`
contract behind the exact flag `ONYX_PHASE9_INTELLIGENCE_INGESTION_V1`. It
accepts already-collected raw items (it does not fetch them), and for each:
normalises publication and event time independently to UTC, denies a publication
time in the future, computes an integer freshness in hours from an injected
clock, assigns a recycled-story content signature over the normalised
(category, headline) tokens, types every claim against the closed
fact/inference/scenario/recommendation set, tags source health against a fixed
tier ladder, and marks a consequential claim corroborated only when it cites at
least one source distinct from the item's own source. It returns a frozen
`IngestionResultV1` record with per-item duplicate linkage (earliest publication is
canonical), the count of uncorroborated consequential claims, the unverified
source count and per-category counts. The session is built through a sealed
factory that returns `None` when the flag is unset and otherwise entry-binds to
the accepted Phase 8 exit evidence by SHA-256 before constructing.

## Consequences

- The slice proves the ingestion-normalisation contract only: temporal
  separation, recycled-story dedup, claim typing, source-health tagging,
  freshness and consequential-claim corroboration.
- It fetches no source, opens no network, calls no model, persists nothing and
  takes no action — in particular it can never turn a headline into a trade.
- Live source ingestion, transparent opportunity scoring, conflicting-claim
  detection and the licence-gated World Monitor connector are explicitly out of
  scope for later gated successors; general open-text/NLP claim understanding is
  not claimed by this deterministic slice.
- The result is default-off and unwired: no startup, voice, UI or dashboard
  path constructs it.

## Alternatives considered

- Fetching primary sources directly in V1: rejected — live ingestion is a
  separate gated surface with its own consent, rate-limit and source-health
  evidence; folding it in would widen default authority.
- Inferring claim types with a model: rejected — a deterministic closed
  taxonomy is auditable and testable, and keeps the slice model-free and
  side-effect-free; model-assisted typing belongs to a later, separately
  evaluated successor.
