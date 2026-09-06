# ADR-0057 — Guild execution-intent binding V1

## Status

Proposed (candidate E1–E5 complete, E6 pending).

## Context

The guild's descriptive substrate is accepted (A9.1 authority, A9.2
stories/QA, A9.3 workflows). The owner's mandate is autonomous development
with owner-gated outward action. Before any dispatch can exist, the bridge
itself must be a validated contract: *what would run, for which story, by
which authorized role, over which bounded scope, against which exact
autopilot*. This ADR records that fourth slice.

## Decision

Add `core/guild_execution_intent_v1.py`, default-off
(`ONYX_GUILD_EXECUTION_INTENT_V1`), deterministic, hermetic; entry-bound to
the A9.3 four-file acceptance tuple **and** to the exact Phase 11 autopilot
bytes (`core/phase11_project_autopilot_v1.py`, 185,305 bytes, SHA-256
`a5dc26eb…`, still declaring `MISSION_TYPE = "project_autopilot_v1"`);
consuming exact A9.1/A9.2/A9.3 snapshots. It enforces, structurally:

1. **Version-pinned target** — a drifted or absent autopilot denies
   construction; intents can never point at unreviewed execution machinery.
2. **Forward-only binding** — an intent binds the exact next uncompleted
   stage of a known run; completed/skipped/out-of-order stages and
   story/run mismatches reject; at most one open intent per (run, stage).
3. **Authority coupling** — the assignee must hold the stage's required
   operation under the registry, exclusive owner sets respected.
4. **Bounded scope** — non-empty workspace-relative `patch_scope` under a
   closed POSIX-form grammar (no traversal/absolute/backslash/dot parts),
   byte-capped `gate_argv_shape` tokens.
5. **Owner-gated by construction** — `requires_owner_approval` must be
   exactly `True`; `is_dispatchable()` is structurally `False`. Dispatch
   arrives only with a later slice under session grants, the approval
   inbox, cost budgets and the kill switch (the owner's termination rule).

The module calls no model, opens no network, spawns no process, persists
nothing and takes no action.

## Consequences

- The future dispatcher can only ever execute an intent this substrate has
  already validated — the guild's authority discipline reaches the edge of
  execution without crossing it.
- Autopilot upgrades are governed: new autopilot bytes require a reviewed
  re-pin of this slice (successor), never a silent retarget.
- Any regression in the pins, the forward-only rule, the authority/scope
  gates, the entry-bind or the cumulative gate fails the slice verifier.

## Alternatives considered

- Binding directly to MissionStore records now: rejected — dispatch
  coupling belongs to the slice that also carries grants, approvals and
  budgets; intents must exist first as inert, reviewable records.
- Allowing `is_dispatchable` to consult the feature flag: rejected — in V1
  the answer must be structurally false, not configuration-dependent.
- Free-form patch scopes: rejected — unbounded scopes are exactly how an
  intent would smuggle authority; the closed grammar mirrors the
  autopilot's own path discipline.
