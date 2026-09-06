# ADR-0003: Normalize connectors through Capability Nexus and governed MCP adapters

- Status: Accepted for phased implementation after the Phase 4 trust foundation
- Date: 2026-07-14
- Decision owners: Cyryx Labs / Onyx owner

## Context

Onyx currently declares tools in `main.py:TOOL_DECLARATIONS` and dispatches them through `OnyxLive._execute_tool` after the host permission broker. These tools are real compatibility contracts, but they do not expose one versioned connector model for health, scopes, rate limits, idempotency, receipts, reconciliation or degraded behavior. The master plan also requires MCP without allowing a remote server, model or tool description to become an authority principal.

Replacing the dispatcher or silently treating browser automation as an official API would break the stable core and obscure access limitations. Adding each provider with unique authorization and result rules would create inconsistent security boundaries.

## Decision

Create a feature-flagged `CapabilityNexus` registry around, not instead of, the current dispatcher. Every entry has a versioned descriptor and a narrow adapter contract covering:

- capability ID/version, provider, operations and truthful status;
- health, authenticated account/tenant, granted scopes, API/version and quota;
- explicit `read`, `draft`, `mutate`, `verify` and `reconcile` separation;
- workspace credential alias and profile binding, never secret values;
- target/domain allowlists, data-class ceiling and provider policy metadata;
- pagination, rate-limit/backoff, timeout and cancellation semantics;
- dry-run/test-account support where the provider offers it;
- stable idempotency key and normalized immutable payload digest;
- `ActionRequest`, permission/audit reference, `ActionReceipt` and observed final state;
- cost/quota telemetry and a truthful degraded/blocked reason.

Current tools first register as `legacy` descriptors without changing their names, arguments, policies, dispatch or default behavior. A descriptor never authorizes execution. All local, API, CLI/SDK, MCP and browser adapters return through the existing permission, audit, mission and verifier boundaries.

The integration preference is official API, official CLI/SDK, governed MCP, then an explicitly authorized browser/UI fallback. Each is a separate capability. Missing API scope never silently selects the fallback.

## MCP boundary

- MCP server metadata, prompts, resources and tool results are untrusted data.
- An MCP tool is disabled until its server identity, transport, version, operations, data classes and workspace allowlist are configured.
- Model-supplied server, grant, approval, credential alias, risk or status fields cannot authorize or lower risk.
- MCP client and any future MCP server surface use typed schemas, bounded payloads, cancellation and correlation IDs.
- An Onyx MCP server exposes only application services already governed by the host; it never exposes database handles, credential values or raw dispatcher bypasses.
- Unknown/disconnected/version-drifted MCP state fails closed and reports `BLOCKED_BY_ACCESS`, `BLOCKED_BY_PLATFORM` or the applicable limitation.

## Rollout

1. Register legacy descriptors in shadow/read-only projection mode.
2. Prove the shared contract with one provider-free local read adapter.
3. Prove one explicitly configured local MCP read adapter.
4. Add one external provider/test-account health/read slice.
5. Progress to draft, then one reversible mutation only after receipts, observation, revoke and failure tests pass.
6. No second provider in the domain starts before the first vertical slice checkpoint is accepted.

## Failure and reconciliation

A pre-dispatch denial or deterministic provider rejection is `failed` with a typed error. A timeout or connection loss after dispatch is `unknown`; the adapter retains idempotency/provider IDs, moves the mission to waiting/reconciliation and never retries the mutation until provider state is observed. Scope loss, account drift or version drift disables the capability rather than broadening access or falling back silently.

## Verification

- Legacy tools produce identical declaration, policy, dispatch and result behavior with Nexus flags off.
- Every registered operation has a host policy; unknown capability/operation denies.
- Shared contract tests cover health, missing/expired auth, wrong workspace/account/target, pagination, rate limit, cancellation, timeout-before/after dispatch, idempotency, duplicate response, reconcile, revoke and degraded mode.
- MCP tests cover malicious descriptions/results, schema overflow, server identity/version drift, disconnect and model-supplied authority fields.
- Every successful external mutation has an exact request, authorization/audit evidence, receipt and observed state; every unknown effect remains unresolved until reconciled.
- Secrets and uncontrolled sensitive payloads never enter descriptors, ordinary logs, mission events or MCP metadata.

## Rollback

Disable connector descriptors and Nexus/MCP feature flags, revoke the affected credential alias and stop new adapter dispatch. Existing direct tools continue through the unchanged dispatcher and permission broker. Preserve requests/receipts for audit and reconciliation; never delete an unknown external effect or retry it blindly.

## Rejected alternatives

- Replace `OnyxLive._execute_tool` with an unrelated framework: duplicates the stable dispatcher and policy boundary.
- Let adapters call providers directly from UI or Operator Cells: bypasses permission, audit and verification.
- Treat MCP discovery as installation or authorization: lets untrusted metadata widen authority.
- Use browser automation as an invisible universal fallback: hides missing scopes, provider state and terms.
