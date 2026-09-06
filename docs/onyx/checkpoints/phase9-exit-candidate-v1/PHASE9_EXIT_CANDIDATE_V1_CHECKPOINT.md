# Phase 9 exit candidate V1 checkpoint

This aggregate, verification-only checkpoint binds the three independently
E6-accepted Phase 9 intelligence-radar slices — intelligence ingestion V1,
opportunity scoring V1 and approved-source live ingestion V1 — to the Phase 9
PRD requirements. It adds no code module, feature flag or runtime wiring.

The coverage map pins each accepted slice by its four-file acceptance tuple
(candidate manifest, acceptance record, acceptance metadata and SHA anchor),
for twelve accepted-component-root files across three slices, and maps each
bound Phase 9 requirement (official-source-first ingestion with
publication/event-time separation, recycled-story deduplication and
fact/inference/scenario/recommendation typing; transparent twelve-dimension
opportunity scoring; and a route-pinned approved-source live-connector contract)
to its satisfying `VE-*` evidence. The verifier machine-checks that mapping:
every accepted slice has exactly one requirement citing exactly its accepted
identifier.

The cumulative selection reproduces 472 passing tests and 80 passing subtests
across twenty-three fresh Python processes — the seven inherited Phase 7
stable-core files, five shared control-plane/registry/memory/ledger/artifact
files, the eight Phase 8 connector test files and the three Phase 9 intelligence
test files — with eight inherited, explained platform-specific skips and zero
failure/error.

Scope and limits: this is the **default-off intelligence/opportunity/
live-connector contract layer only**. Every claim binds exactly the three
accepted E6 envelopes, each of which is deterministic (ingestion/scoring) or a
route-pinned, redirect-disabled, hermetic contract (live connector) that
performs no real network I/O in evidence. No live execution is bound or claimed
here — the approved-source live ingestion run is owner-gated and unbound. World
Monitor is **excluded**: while `BLOCKED_BY_LICENSE` it has no accepted evidence,
and this aggregate copies none of its UI/assets/source and implies no Cyryx
ownership. Consistent with the PRD guard, nothing here turns geopolitical or
financial headlines into autonomous trading actions. The aggregate claims no
startup/voice/UI/dashboard wiring, no Phase 10–16 work and no full Onyx PRD
completion.
