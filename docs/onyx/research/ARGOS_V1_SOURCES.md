# Argos V1 — sources and design basis

Hermetic, deterministic world-signal registry. No external service is used;
no third-party world-monitoring source is consulted or copied.

## Basis

- `OPEN_SOURCE_AND_API_LICENSE_REVIEW.md` (Argos entry): original
  100%-proprietary Cyryx work replacing the dropped third-party World
  Monitor; no third-party source license; per-provider API terms apply only
  to a later owner-gated live fetch.
- Capability matrix row "Argos world-intelligence (proprietary)":
  `NOT_IMPLEMENTED` until a slice is built and E6-accepted under the
  standard evidence chain — this slice.
- Accepted Phase 9 pipeline: ingestion/scoring contracts (the consumer) and
  the live-ingestion connector (the only later path to real network, owner
  gated); the Phase 9 rule "a score/item can never trigger an action" is
  inherited as `is_actionable()` structurally False.

## Design decisions

- **Rights-noted sources** — registration requires a `rights_note`;
  citation honesty starts at the registry, not the report.
- **Closed taxonomies** — 8 categories, 4 source kinds; unknown values
  reject.
- **Injected time, bounded scores** — deterministic and clock-free.
- **Deterministic briefs** — weight desc, id asc, bounded limit.
- **Entry-bound** to the accepted Phase 9 exit tuple.
