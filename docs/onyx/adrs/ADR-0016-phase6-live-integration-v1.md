# ADR-0016: Default-off Phase 6 V6 live-integration facade V1

Status: Candidate — additive, default-off, not live

Date: 2026-07-23

## Context

Agentic Core V6 is accepted only as an isolated implementation handoff. Its
accepted boundary explicitly excludes provider adapters, the Phase 5
`local_catalog` binding, external-agent execution and live wiring. The current
standalone text path remains `core/llm_client.py`; the accepted provider-free
catalog authority remains `Phase5IntegrationV3`; `MissionStore` remains the
only mission executor.

The first integration slice must connect those exact seams without modifying
their frozen bytes, changing existing call sites, routing Gemini Live through
the standalone text path, adding a generic executor, or enabling a feature in
the live host.

## Decision

Add `core/phase6_live_integration_v1.py` behind the exact
`ONYX_PHASE6_LIVE_INTEGRATION_V1=true` gate. Its factory returns `None` before
dependency validation or construction when the gate is off. No live module
imports or constructs the facade.

### Current standalone text compatibility adapter

`CurrentTextProviderAdapterV1` characterizes the existing
`get_llm_provider()`, `get_llm_settings()` and `call_llm_text()` seam through
lazy imports. It does not edit or replace their call sites.

V1 admits only loopback HTTP(S) endpoints without URL credentials, query or
fragment. A non-loopback or credentialed endpoint is `BLOCKED_BY_POLICY`.
Workspace and data class are hard filters before invocation; price and quality
cannot override them. The request reserves the current client's fixed
600-output-token ceiling, exactly one API call and zero cost. The call runs in
the accepted terminable process executor under the request wall deadline. That
dedicated child pins the characterized provider, endpoint and model inputs
around the unchanged call so a later configuration-file change cannot cross an
already-authorized route.

Cancellation before dispatch spends no call/token budget. A provider result
that completed before a racing cancellation remains authoritative and is
receipted as such. Timeout terminates the provider process. Errors are reduced
to a stable taxonomy; exception messages, prompt, system text, output, endpoint
and model never enter the receipt. V1 does not silently select another
provider. The unchanged caller path is the explicit fallback whenever this
extension is absent or reports unavailable.

This adapter is standalone text only. It does not claim Gemini Live audio,
streaming or structured-plan parity and does not route either modality through
the other.

### Exact Phase 5 catalog binding

`LocalCatalogReadBindingV1` accepts only an exact
`Phase5IntegrationV3` instance and only the closed
`local_catalog_read` schema (`page_size`, `cursor`). It binds the same workspace
and an explicit maximum data class, obtains authorization through
`permission_hook()`, then dispatches only `catalog_read()`. There is no generic
tool or provider executor.

Completed Phase 5 reads produce a separate immutable receipt containing
digests, item count, zero cost and `egress=none`; raw cursor and catalog items
are excluded. An additive authenticated SQLite store makes exact replay
idempotent and rejects changed-input reuse of a request ID.

Agentic Core V6 still materializes a catalog-only plan to
`WAITING_FOR_PHASE5`, with no MissionStore mission. The integration returns the
authoritative Phase 5 result and durable receipt but does not force the frozen
V6 projection through an unsupported completion transition. This is truthful
partial integration, not Phase 6 exit.

### External agent

The facade exposes only the existing `DisabledExternalAgentAdapterV1`.
Its status remains `BLOCKED_BY_ACCESS`; V1 contains no browser workaround,
subprocess agent, session or follow-up implementation.

## Consequences

- Agentic Core V1-V6, MissionStore, Phase 5, `llm_client.py`, `main.py`,
  `ui.py`, dashboard, Activation V6, accepted manifests and configuration stay
  byte-exact.
- Extension-off behavior is the current host behavior. No restart, provider
  call, network call, configuration write or live activation is part of this
  checkpoint.
- The standalone text adapter has no token-usage response from the existing
  client, so it reserves the full 600-token ceiling rather than claiming exact
  usage.
- A Phase 5 catalog receipt is durable execution evidence, while the frozen V6
  plan truthfully remains `WAITING_FOR_PHASE5`.
- Provider-backed planning, Gemini Live compatibility, planner memory,
  installed external agents and host activation remain later independently
  gated slices.

## Rollback

Leave the new flag unset or false and do not construct the facade. Existing
text callers continue directly through `core/llm_client.py`; Gemini Live
continues through `OnyxLive`/`resolve_live_model`; existing mission and Phase 5
dispatch remain unchanged. The additive receipt sidecar may be retained for
diagnosis/export and is never merged into MissionStore.

## Rejected alternatives

- Editing `llm_client.py` or existing call sites: rejected because compatibility
  must be characterized around frozen behavior.
- Treating an OpenAI-compatible remote URL as local: rejected because an outage
  or lower price cannot widen privacy.
- Falling back from standalone text to Gemini Live or vice versa: rejected
  because modality parity is unproved.
- Calling Phase 5 through a generic executor: rejected because it would bypass
  the accepted authorization-to-dispatch seal.
- Marking the frozen V6 plan complete after a sidecar read: rejected because
  V6 has no accepted `WAITING_FOR_PHASE5 -> COMPLETE` transition.
- Activating an external agent or browser fallback: rejected because access,
  authentication and an independently reviewed runtime do not exist.
