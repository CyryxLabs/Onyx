# Story ONYX-ARGOS-V1 — Argos World-Intelligence Registry V1

**Status:** Done (accepted 2026-08-19, `VE-ARGOS-V1-E6-001`, root
`11f51eb8…`; acceptance verifier reproduced the full 33-file gate
868/0/0/17/96; autonomous-session honesty boundary recorded; matrix/ledger
updates batched into the V54 pass)
**Epic:** Argos (plan item A13 — proprietary world-intelligence, replaces
the dropped third-party World Monitor)
**Predecessor:** `VE-P9-EXIT-CANDIDATE-V1-E6-001` (Phase 9 exit)

## Story

As the Cyryx Labs owner, I want Onyx to hold a **proprietary, cited
world-signal registry** — registered sources with rights notes, categorized
and scored signals, and a deterministic brief — so world awareness feeds the
Phase 9 intelligence pipeline from 100% first-party code, with the standing
guard that a signal can never trigger an action.

## Design

Module `core/argos_v1.py`, flag `ONYX_ARGOS_V1`, default-off, deterministic,
hermetic; entry-bound to the Phase 9 exit four-file acceptance tuple.
Original Cyryx work: no third-party source is copied (the dropped World
Monitor contributes nothing).

- `ArgosSourceV1`: registered source with closed `kind`
  (`market_data/official/press/social`) and a **required `rights_note`** —
  the license-honesty discipline at the data layer.
- `WorldSignalV1`: closed category taxonomy
  (climate/culture/geopolitics/health/markets/regulation/security/
  technology), region, headline, **registered source only**, injected
  integer `observed_at` (no clock read), severity and confidence each 1–5.
- Sealed `ArgosRegistryV1`: unique ids, closed vocabularies, caps;
  projections `signals_for(category)` and `brief(limit)` ranked by
  severity×confidence with deterministic ties; `is_actionable()`
  **structurally False** — Argos informs, it never acts (the Phase 9 rule).

## Acceptance criteria

1. [ ] Contracts as designed; default-off; hermetic; no action surface;
       `is_actionable` structurally False.
2. [ ] Unregistered source, missing rights note, unknown
       category/kind, out-of-range severity/confidence/observed_at →
       rejected.
3. [ ] Deterministic ranking (weight desc, id asc) in `signals_for` and
       `brief`; limit bounds enforced.
4. [ ] Entry-bind to the Phase 9 exit tuple; ≥30 adversarial tests;
       33-file gate after tonight's seals; standard chain + E6 with the
       autonomous-session honesty boundary.
5. [ ] Matrix rows (Argos → contract accepted; world-intelligence honest
       limitations) in the following documentation-authority pass.

## Out of scope

Live fetching (owner-gated egress via the accepted Phase 9 live-ingestion
connector), provider adapters, scheduling, any action or runtime wiring.

## File List

- `docs/stories/ONYX-ARGOS-V1.story.md` (this story)

## Change Log

- 2026-08-18: Opened while the R15B soak (attempt 3) runs.
