# ADR-0032 — Phase 7 Founder Command V1

- Status: candidate
- Date: 2026-07-23
- Depends on: accepted Approved Sources + Company Graph V1

## Context

The PRD requires a cited Daily Founder Brief, weekly operating review,
portfolio view, blocker/dependency report, decision queue, source-grounded
revenue opportunity queue, risk register, change delta and top three
recommended actions. Decision-critical output must distinguish known,
inferred and unknown information and include alternatives, verification and
completion evidence without inventing revenue, customers, traction, runway or
market validation.

The accepted Company Graph provides current source-grounded items but does not
classify operational freshness, detect undeclared incompatible statuses,
compare successive briefs or rank explicit action candidates.

## Decision

Add an exactly default-off `FounderCommandGeneratorV1` sealed to the accepted
Company Graph projector and a complete explicit per-semantic freshness policy.
The generator calls the projector itself rather than accepting a caller-forged
graph snapshot.

The generated `FounderCommandBriefV1` is deterministic, content-addressed and
read-only. It contains:

- all cited graph items and known/inferred/unknown indexes;
- current/aging/stale status with refresh and stale deadlines;
- declared contradictions plus deterministic potential conflicts where active
  claims about the same fact/status/metric subject carry incompatible states
  without contradiction or supersession;
- portfolio, critical blocker, dependency, proposed-decision and risk views;
- explicitly supplied, graph-evidence-linked revenue opportunities;
- top three actions ranked by impact, urgency, graph confidence, effort and
  downside;
- known context, inference, unknowns, alternative explanations, recommended
  action, verification method, completion evidence and downside for every
  action;
- authenticated “what changed since last brief” claim and subject deltas.

No opportunity or action is synthesized when none is supplied. The brief
explicitly abstains instead. Daily and weekly cadences use the same source and
truth contract.

The brief digest covers all item, freshness, contradiction, portfolio, queue,
recommendation, delta, trust and abstention fields. Previous briefs are
rehash-verified and must match workspace, principal and chronology.

## Consequences

- Material queues contain only graph claim IDs whose items carry citations.
- Revenue claims and estimates cannot enter through an uncited free-text
  summary.
- Stale data remains visible and is never silently treated as current.
- The module adds no persistence, source fetch, model call, execution,
  provider, browser, process, network, UI or live-runtime seam.
- General open-text/NLP contradiction discovery remains unimplemented; V1
  detects declared conflicts and structured incompatible status conflicts.

## Rollback

Leave `ONYX_PHASE7_FOUNDER_COMMAND_V1` unset. The factory returns before
accepted-entry verification or graph binding. No brief is persisted and all
existing V13, graph, source, memory and alias behavior remains unchanged.
