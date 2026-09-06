# ADR-0001: Extend the stable core instead of replacing it

- Status: Accepted for planning; implementation gated by Phase 0 review
- Date: 2026-07-14
- Decision owners: Cyryx Labs / Onyx owner

## Context

Onyx already has working contracts for model tool declarations/dispatch, exact host approval, immutable audit, persistent missions with leases/recovery, structured result verification, local memory, OS credential storage, voice/UI/Orb, an authenticated dashboard and native packaging. The governed-operations plan adds workspaces, typed evidence/actions, grants, connectors, model routing, Operator Cells and a richer UI.

A wholesale rebuild would duplicate security boundaries, invalidate migrations/tests and create two sources of truth. Extending arbitrary internals directly would also risk accidental behavior changes.

## Decision

Treat the following as the stable core: `MissionStore`/`MissionWorker`, `authorize*`/exact request digest, `OnyxLive._execute_tool`, `approved_execution`, mission workspace tools, `tool_audit`, `MemoryStore`/memory compatibility API, credential vault helpers, `OnyxUI` callbacks/dashboard protocol, `resource_root`/`data_root` and package smoke contract.

Add capabilities only through versioned adapters, registries, typed envelopes, events and sidecar tables. There remains exactly one mission executor, permission boundary, model tool dispatcher and memory compatibility API. New components call back through those boundaries and cannot perform direct provider/local mutations.

Existing behavior stays the default until a feature-flagged extension passes characterization, compatibility, security, migration and rollback tests. Unknown extension state fails closed without weakening legacy behavior.

## Consequences

Positive:

- Current verified tools/features remain available.
- Security fixes and regression coverage apply to new capabilities.
- Extensions can be disabled without reverse-migrating core databases.
- Connector/model/UI evolution is provider- and presentation-agnostic.

Costs:

- Adapters and projections add explicit integration work.
- Rich operational phases must map onto current mission states.
- Some legacy APIs require compatibility shims longer than a rewrite would.

Rejected alternatives:

- Replace the mission engine with a new orchestration framework: rejected because it duplicates leases, recovery, approvals and audit.
- Add direct connector calls from UI/operators: rejected because it bypasses policy, receipts and verification.
- Globally rename/rewrite persisted data: rejected because legacy migrations already preserve owner state.

## Compatibility contract

No removal/rename/semantic change to a stable public method, persisted field, tool name or UI callback without: a versioned adapter; idempotent migration; dual-read/fixture proof; explicit deprecation; rollback; and regression tests. Feature flags default off. Core database schema versions newer than runtime continue to fail closed.

## Migration and rollback

1. Freeze characterization fixtures and contract tests.
2. Add sidecar/adapter code with flags off.
3. Run shadow projections/evaluators and compare with current outcomes.
4. Activate one vertical slice at a time.

Rollback disables the extension flags and connector descriptors. Current mission, memory, credential, UI and dashboard paths continue unchanged. Sidecar records are retained for audit/export and never copied destructively into core databases.

## Verification

- Existing unit/browser/package tests remain green with flags off and on where applicable.
- Old mission/memory/database fixtures produce identical legacy API results.
- No source scan or runtime trace shows connector/operator/UI code bypassing `authorize_model_tool`/`authorize_mission_tool` and audit.
- Sidecar unavailable/corrupt never broadens authority.
- Feature rollback requires no destructive data operation.

## Revisit triggers

Revisit only if evidence shows a stable core contract cannot satisfy a mandatory requirement, or a security/license/platform issue forces replacement. The replacement still needs a parallel versioned migration and proven rollback; convenience is insufficient.
