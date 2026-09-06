# Phase 6 Exit Candidate V1 checkpoint

Status: **E1-E5 candidate ready; aggregate E6 pending; Phase 6 not exited**

Date: 2026-07-23

## Scope

This checkpoint composes the current Phase 6 implementation and evidence into
one read-only gate. It does not add a runtime seam, provider route, process,
network call, MCP dispatch, external-agent authority, persistent state, or
Phase 7 authority.

## E1 — scope and blockers

The enabled candidate requires the exact accepted roots for:

- Agentic Core V6 and Live Integration V2;
- Gemini Live and local/text compatibility as separate modalities;
- Provider Registry V1;
- provider-free Research and independent Verifier Cells;
- Local MCP V1 plus its C002 Activation V10 C003 dependency reacceptance;
- Unified Router V1 C002;
- the disabled External-Agent descriptor;
- Live Wiring V1;
- frozen Live Wiring V2 and its current verifier;
- V13 source/bootstrap/launcher/test roots and its dated operational record.

The external-agent integration remains `BLOCKED_BY_ACCESS`. Router V1 remains
local/private-only. No additional provider or cross-route is in this slice.

## E2 — capability delta

`docs/onyx/CAPABILITY_MATRIX.md` contains the section
`Phase 6 E1-E5 exit candidate V1 (E6 pending)`, and
`CAPABILITY_DELTA_SNAPSHOT.md` freezes its E1-E5 meaning for this candidate.
The live matrix remains editable for a later E6 transition. The delta records
before/after status, exact evidence, limitations, owner, and next action for
the affected capabilities. No status overstates permanent provider
availability, MCP dispatch, external-agent authority, or aggregate Phase 6
acceptance.

## E3 — verification bundle

- Base commit: `b2dc0b21f487013cebec34bb148ffb1aeb02611a`
- Tree state: dirty development worktree; the content-addressed candidate
  manifest is authoritative for this checkpoint.
- Platform: Windows 11 `10.0.26200`, x64
- Python: CPython 3.13.7 x64
- Pytest: 9.1.1
- google-genai: 2.11.0
- Execution: one selected test file per fresh Python process
- Result before manifest freeze: **294 passed, 0 failed, 0 errors, 0 skipped**
- Ruff lint: passed
- Ruff format: passed
- Python byte compilation: passed

The selection is recorded in `cumulative-selection.json`. A non-fatal Windows
Qt `IUnknown` release diagnostic appeared after one process had already
returned success; it produced no failed/error/skip result and is retained as a
teardown advisory rather than represented as a product failure.

## E4 — safety and rollback

Twenty candidate-focused tests cover:

- exact flag parsing and return-before-filesystem default-off behavior;
- sealed gate construction;
- full-root rehash and one-byte tamper denial;
- duplicate-key JSON denial;
- decision/finding drift;
- missing modality/component denial;
- no silent retry or cross-routing;
- hard privacy before remote fallback;
- research/verifier separation and no self-certification;
- zero network/provider/process/live call counters;
- Local MCP C002 dependency truth;
- disabled external-agent authority;
- V13 point-in-time versus permanent-availability truth;
- matrix-delta presence without E6 self-acceptance;
- read-only filesystem behavior;
- absence from startup/live surfaces;
- report-level overclaim denial.

Rollback is omission or disablement of
`ONYX_PHASE6_EXIT_CANDIDATE_V1`. No runtime restart or data migration is
required because the candidate creates no state and patches no seam.

## E5 — package and operational limits

- ADR: `ADR-0028-phase6-exit-candidate-v1.md`
- API delta: one sealed feature gate, one immutable report, one factory
- Schema/event delta: none
- Migration: none
- Threat delta: evidence-path, duplicate-JSON, root-drift, modality-crossing,
  privacy-fallback, self-certification, and authority-overclaim denial
- Resource/cost impact: bounded local file hashing and strict JSON parsing only
- Provider/network/process/live calls: zero
- Runtime activation: none
- Reconcile/revoke: not applicable; no external action or state exists
- Kill/rollback: disable or omit the candidate flag

## E6 — pending

This checkpoint does **not** accept itself. A separately frozen verifier,
acceptance record, acceptance metadata, and acceptance test must independently
reproduce this exact manifest and the proportional regression selection.

Until that decision is accepted:

- `phase6_exit=false`;
- `phase7_unlocked=false`;
- no additional provider/cross-route is authorized;
- the External-Agent descriptor remains blocked;
- the full Onyx PRD remains incomplete.
