# Phase 7 Layered Memory V1 — E6 acceptance

- Evidence ID: `VE-P7-LAYERED-MEMORY-V1-E6-001`
- Decision date: `2026-07-23`
- Decision: **ACCEPTED — default-off governed seven-layer memory**
- Candidate manifest:
  `2818c6ffe66681436286d89f557c57cd23c35c29ee7f29d53d7eb2bf9d8ec95d`
- Artifact root:
  `96218afa17936918aaed3bc4f225db3fee0eb117fa4e94f9439d93d1f6ed1020`

## Decision

Layered Memory V1 is accepted as the next ordered Phase 7 slice. Findings are
`P0=0`, `P1=0`, `P2=0`, and `P3=0`.

The independent gate:

- rehashed all seven candidate artifacts and recomputed the artifact root;
- rehashed all four accepted Workspace Memory V1 entry roots;
- confirmed the accepted Workspace Memory implementation remained unchanged;
- reproduced exact default-off return-before-entry behavior;
- executed layered-memory, Workspace Memory, alias, control-plane, workspace,
  MemoryStore, approved-source, Company Graph and Founder Command suites in
  fresh Python processes;
- reproduced **161 passed tests, 77 passed subtests, 0 failed, 0 errors**;
- reproduced one explained Windows skip for a POSIX-only mode assertion;
- confirmed no global vector index, network/process/provider/model/browser/
  action/live call or startup seam.

## Accepted behavior

The accepted catalog:

- stores typed session-working, episodic-mission, semantic-institutional,
  decision, procedural, preference and temporal-status memory;
- binds every operation to an active workspace, principal, control-plane
  connection and HMAC key;
- uses normalized content-addressed identity and explicit entity resolution;
- requires correction, supersession or contradiction links for a competing
  live value of the same entity;
- applies atomic candidate/approved/rejected/superseded/corrected/deleted
  lifecycle transitions;
- filters authorization, lifecycle, source, sensitivity, validity and
  freshness before ranking;
- supports scoped deterministic export, retention enforcement, principal
  deletion and source deletion;
- scrubs content, source IDs, tags and entity labels into signed tombstones;
- classifies prompt-injection signals, rejects secret-like content and keeps
  all memory as untrusted evidence with no instruction authority;
- coexists with the accepted Workspace Memory V1 sidecars without modifying or
  disrupting them.

## Limits retained

- V1 remains default-off and is not wired to V13, startup, voice, UI or the
  dashboard.
- General NLP entity extraction is not implemented; records require explicit
  typed entity keys and relations.
- Governed multi-format document ingestion, granular citations, version
  comparison and render/visual QA remain pending.
- Phase 7 is not exited and the full Onyx PRD is incomplete.

The next gate will implement governed document ingestion over the accepted
source, graph and memory roots before aggregating the Phase 7 exit.
