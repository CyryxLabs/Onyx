# ADR-0017: Identity-bound sealed Phase 6 live-integration facade V2

Status: Candidate — additive, default-off, not live

Date: 2026-07-23

## Context

Phase 6 Live Integration V1 was rejected by an independent gate. V1 bound
workspace authority but did not bind the complete host identity
`workspace_id + account_id + profile_id + principal_id` into every integration
request and receipt. Its operational constructors also admitted a caller
supplied text invoker and executor. V1 is preserved byte-exact, default-off and
unwired so the rejection remains reproducible.

Agentic Core V6, Phase 5 Integration V3, MissionStore and the current
standalone text seam remain frozen authorities. V2 must close the two rejected
boundaries without modifying or activating them.

## Decision

Add `core/phase6_live_integration_v2.py` behind the exact
`ONYX_PHASE6_LIVE_INTEGRATION_V2=true` gate. The factory returns `None` before
validating dependencies, constructing an executor or writing a receipt file
when the gate is off. No live surface imports the V2 module.

### Complete immutable host identity

`HostIdentityBindingV2` is a frozen value containing exactly workspace,
account, profile and principal identifiers. Before operational construction it
compares:

- workspace against Agentic Core V6 workspace authority; and
- workspace, account, profile and principal against the exact
  `Phase5IntegrationV3` binding and principal.

The complete identity payload and its canonical digest are present in every V2
text/catalog request digest and every V2 text/catalog receipt digest. Catalog
receipt persistence also indexes request digest and identity digest. Replay
under another account, profile, principal, workspace or changed input fails
closed.

The facade, text adapter and catalog binding re-attest their authorities before
each operation. Post-construction identity or dependency drift therefore
cannot be treated as the original host.

### Sealed operational text construction

The public V2 factory accepts no invoker, executor or prebuilt adapter.
`CurrentTextProviderAdapterV2` accepts only the complete identity and
internally constructs the exact frozen V1 compatibility adapter with:

- the captured exact `_current_llm_text_call` seam;
- the current characterized provider configuration;
- an exact `TerminableProcessExecutorV4`; and
- the confidential maximum data class.

Operational attestation verifies the exact delegate type, invoker object,
executor type and workspace descriptor before invocation and close. Replacing
the invoker or executor after construction is denied. V2 inherits V1's bounded
process timeout, endpoint/model pinning, cancellation, privacy and receipt
redaction behavior rather than introducing another provider path.

### Catalog and external-agent boundaries

The V2 catalog binding composes the exact V1 closed
`local_catalog_read` binding and exact Phase 5 V3 authority. It adds the full
identity envelope and authenticated append-only V2 receipt store; it does not
add a generic tool executor. Agentic Core still produces
`WAITING_FOR_PHASE5`, no MissionStore mission is invented and no unsupported
completion transition is forced.

The facade exposes only `DisabledExternalAgentAdapterV1`; external execution
remains `BLOCKED_BY_ACCESS`.

## Consequences

- V1 code, tests, ADR, checkpoint, verifier, manifest and artifact root remain
  byte-exact and explicitly rejected.
- Agentic Core V1-V6, Phase 5 V3, MissionStore, current LLM client and all live
  surfaces remain unchanged.
- Off is behaviorally inert. V2 creates no process, file or network activity
  until exact opt-in and complete authority attestation.
- V2 closes the two V1 P1 findings but does not authorize activation, Gemini
  Live cross-routing, provider-backed planning, external agents or Phase 6
  exit.

## Rollback

Leave the V2 flag unset or not exactly `true` and do not construct the facade.
No live path references V2. Additive V2 receipt sidecars can be retained as
audit evidence and are never merged into MissionStore.

## Rejected alternatives

- Editing V1: rejected because the failed candidate and its evidence must stay
  reproducible.
- Deriving account/profile/principal from workspace: rejected because those
  are independent host authorities.
- Accepting a prebuilt adapter for testability: rejected because it reopens the
  operational substitution path.
- Accepting subclasses or protocol-compatible executors: rejected because the
  operational factory must attest the exact accepted process executor.
- Adding V2 directly to `main.py`, UI, dashboard or a launcher: rejected because
  this checkpoint is an isolated candidate, not activation.

