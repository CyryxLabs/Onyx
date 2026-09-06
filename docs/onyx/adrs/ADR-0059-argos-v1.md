# ADR-0059 — Argos world-intelligence registry V1

## Status

Proposed (candidate E1–E5 complete, E6 pending).

## Context

World-intelligence has been `NOT_IMPLEMENTED` since the third-party World
Monitor was dropped for license reasons; the matrix requires an original,
100% proprietary replacement built under the standard evidence chain (plan
item A13). The accepted Phase 9 pipeline (ingestion, scoring, live
connector) is the consumer this substrate feeds.

## Decision

Add `core/argos_v1.py`, default-off (`ONYX_ARGOS_V1`), deterministic,
hermetic, entry-bound to the accepted Phase 9 exit four-file tuple. Original
Cyryx work — nothing is copied from the dropped World Monitor. Structural
gates: every signal references a registered source and every source carries
a `rights_note`; closed category (8) and source-kind (4) vocabularies;
injected integer `observed_at` (no clock read); severity/confidence each
1–5; deterministic ranking (severity×confidence desc, id asc) in
`signals_for`/`brief` with a bounded limit; `is_actionable()` structurally
False — Argos informs, it never acts (the accepted Phase 9 rule inherited
verbatim). The module calls no model, opens no network, spawns no process,
persists nothing and takes no action.

## Consequences

- The world-intelligence row gains a first-party, accepted foundation; the
  owner-gated live fetch can later feed Argos through the accepted Phase 9
  live-ingestion connector without new invention.
- Rights honesty exists at the data layer: an unrights-noted source cannot
  be registered.
- Any regression in the citation/taxonomy/bounds/ranking gates, the
  entry-bind or the cumulative gate fails the slice verifier.

## Alternatives considered

- Reusing World Monitor concepts/code: rejected — the replacement must be
  original; only the *need* (world awareness) carries over.
- Free-text categories: rejected — closed taxonomy keeps briefs
  deterministic and comparable.
- An actionability score: rejected — a signal can never trigger an action;
  actionability is unrepresentable here.
