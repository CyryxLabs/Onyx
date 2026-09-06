# Guild handoff V1 — sources and design basis

Hermetic, deterministic story/handoff ledger. No external service is used;
the basis is the first-party AEXOS discipline documents and the accepted
A9.1 registry.

## AEXOS basis (first-party, `CyryxLabs/aexos-engine`)

- Story-driven development and lifecycle: AEXOS Constitution Article III
  (no code without a story, acceptance criteria required, checkbox/File
  List tracking) and the story-lifecycle rules (Draft → validated/approved →
  InProgress → InReview → Done with QA gates).
- QA loop: `qa-loop` workflow — verdicts APPROVE/REJECT/BLOCKED, maximum 5
  iterations, escalation on blocked — encoded as `QA_VERDICTS`,
  `MAX_QA_REJECTS`, reject-covered loop edges and the blocked-stuck rule.
- Handoff compaction: `agent-handoff` rule — ≤5 decisions, ≤10 files,
  ≤3 blockers, ~500-token artifact — encoded as the section caps and the
  4,000-byte hard budget.
- Authority: QA verdicts belong to the `quality_verdicts` constitutional
  owners from the accepted A9.1 matrix (Article II), reused not redefined.

## Design decisions

- **History as data.** Every story carries its full transition history;
  validation replays it against the closed edge set. No clock is read.
- **Count-based loop coverage.** in_review→in_progress edges must be
  covered by reject verdicts (≤ cap); ordered interleaving belongs to A9.3.
- **Registry reuse.** The ledger consumes an exact `GuildRegistrySnapshotV1`
  (A9.1) — roles and QA owners are never redeclared here.
- **Entry-bound.** Construction is denied unless the A9.1 four-file
  acceptance tuple is byte-exact.
- **No execution surface** — later guild slices own all execution.
