# Capability delta — Argos V1

| Field | Before | After |
| --- | --- | --- |
| Argos world-intelligence (proprietary) | `NOT_IMPLEMENTED` | `WORKING_AND_VERIFIED` (registry contract, default-off) |
| Evidence | — | `VE-ARGOS-V1-E6-001` |
| Authority added | — | None — registry + deterministic briefs; `is_actionable` structurally False |
| Live world-signal fetch | owner-gated (absent) | owner-gated (unchanged; later via the accepted Phase 9 live-ingestion connector) |

**What changed.** Onyx has a first-party world-intelligence foundation:
rights-noted sources, a closed signal taxonomy, bounded scores and
deterministic briefs — original Cyryx work under the standard evidence
chain.

**What did not change.** No live fetching, no provider adapter, no action,
no runtime wiring. World awareness still requires the owner-gated live
path to become real; Argos gives it a governed place to land.
