# ADR-0044 — Phase 8 exit candidate V1

## Status

Proposed (candidate E1–E5 complete, E6 pending).

## Context

Phase 8 of the Onyx PRD adds executive-office connectors in the order calendar
read/brief/draft/create, email search/read/draft/send, tasks/notifications, then
Drive/OneDrive and Office, proving one provider (Microsoft Graph) before
generalizing. Seven vertical slices were implemented additively, each exactly
default-off, route-pinned and independently E6-accepted with its own hash-bound
evidence chain: OAuth V1, Read V1, Live Read E2E V1, Calendar V1, Mail V1,
Tasks V1 and OneDrive Read V1. This ADR records the aggregate exit checkpoint
that binds those seven accepted component roots to the Phase 8 PRD requirements
without adding any new runtime authority.

## Decision

Publish an aggregate `phase8-exit-candidate-v1` checkpoint that (1) maps each
Phase 8 PRD **connector** requirement to the accepted `VE-*` evidence that
satisfies it, and machine-verifies that mapping (every accepted slice has
exactly one requirement citing exactly its accepted identifier), (2) pins the
four-file acceptance tuple (candidate manifest, acceptance record, acceptance
metadata and SHA anchor) of each of the seven accepted slices by SHA-256, and
(3) reproduces the complete cumulative Phase 8 gate — the twenty inherited
Phase 7 stable-core and Phase 8 test files — in fresh Python processes. The
checkpoint adds no code module, no feature flag and no wiring; it is a
verification-only aggregation over already-frozen predecessors.

Scope is deliberately the **default-off connector contract layer only**. The
aggregate binds and claims exactly what the seven accepted E6 envelopes
establish — each of which is default-off, route-pinned contract evidence. It
does **not** bind or claim any live execution: no live read, calendar create,
mail send, task create or drive listing is part of this aggregate's bound
evidence, and the frozen acceptance records it pins each report their own live
E2E as pending owner consent plus a confirmed run. (A live read and one live
calendar create were exercised during development and written as unbound runtime
reports under `runtime/phase8-*-e2e/`; those are explicitly outside this
aggregate's bound scope and are not evidence of record here.) The aggregate also
does not cover the PRD's daily-operations behaviours (inbox triage, deadlines/
follow-ups, prep, travel-aware scheduling, task/review cadence, meeting
decision/action reconciliation), which were not built.

## Consequences

- The Phase 8 **connector-layer** default-off implementation is claimed complete
  only for what the seven accepted slices exercise as contract evidence:
  delegated least-scope OAuth, route-pinned read/brief/paging, a contract-proven
  live-read E2E slice, availability plus one exact-grant calendar create,
  exact-recipient content-bound mail draft/send, a deterministic notification
  router plus one exact-grant To Do create, and route-pinned metadata-only
  OneDrive read.
- The checkpoint explicitly does **not** claim any live E2E — for read,
  calendar create, mail send, task create or drive listing — as bound evidence;
  each still needs its own delegated consent plus an explicitly confirmed run,
  and none of that is part of this aggregate's bound scope. It claims no
  startup/voice/UI/dashboard wiring, no PRD daily-operations behaviours, no
  Phase 9–16 work and no full Onyx PRD completion.
- Any regression in an accepted component root, the requirement→evidence mapping,
  or the cumulative gate fails the exit verifier, so the aggregate cannot
  silently drift from its parts.

## Alternatives considered

- Re-hashing each component's full artifact closure instead of its four-file
  acceptance tuple: rejected as redundant, because each acceptance metadata file
  already binds its candidate artifact root, and the tuple is the same anchor
  the individual acceptance verifiers reproduce.
- Deferring the exit checkpoint until live E2E is proven for every mutation
  slice: rejected because live consent is an owner decision outside the default
  -off contract scope; the exit honestly reports live proof as pending per slice.
- Binding `device-bootstrap-v2` as an eighth accepted root: rejected because it
  is a development corrective (device-code sign-in that primes the native vault)
  with no E6 acceptance envelope. Its eight tests remain in the cumulative gate,
  but it is not one of the seven requirement-mapped, envelope-accepted slices.
