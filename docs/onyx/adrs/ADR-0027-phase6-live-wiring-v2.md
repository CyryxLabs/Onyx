# ADR-0027: Session-bound Phase 6 planning composition

Status: Candidate  
Date: 2026-07-23

## Context

Phase 6 Live Wiring V1 already attaches the accepted Agentic Core V6 and Live
Integration V2 to each real Phase 5 session. The accepted provider registry,
research/verifier cells, local MCP identity, unified command router, and
disabled external-agent descriptor still existed as isolated components. They
had no shared session owner and therefore could not be inspected as one
coherent operational composition.

The live Gemini connection must remain unchanged while this composition is
introduced. The accepted Unified Command Router V1 is intentionally
local-private-only. The current Gemini Live provider is remote, so declaring it
as an eligible local route would be false and would weaken the privacy
boundary.

## Decision

Create a strict default-off `Phase6LiveWiringV2` overlay over an already
installed exact `Phase6LiveWiringV1` controller.

The overlay:

- patches only the V1 controller instance callables `_create_session` and
  `_detach_session`;
- changes no host class, UI, voice, tool, network, provider, or Phase 5 seam;
- creates one session-bound Provider Registry V1, Research Verifier Pipeline
  V1, Local MCP identity, Unified Command Router V1, and disabled
  external-agent catalog;
- authenticates all fifteen accepted component evidence roots before
  construction and every later controller attestation;
- uses independent random authentication keys for provider health, research
  evidence, research receipts, router receipts, and external-agent receipts;
- exposes metadata-only `preview` planning and never invokes a provider,
  subprocess, MCP process, network socket, or live integration method;
- truthfully records the remote Gemini adapter as `BLOCKED_BY_POLICY` inside
  the local-only V1 registry;
- closes and removes the V2 operational session before V1 detaches and closes
  its base session;
- restores the exact V1 instance lookup state, including deletion of temporary
  method shadows, during failure or rollback.

## Consequences

This candidate makes the accepted Phase 6 authorities one coherent,
identity-bound session graph without changing the working Gemini voice engine.
Local catalog and authenticated research planning can be represented
immediately. The V1 text route correctly remains blocked by
`local_hard_filter` for Gemini.

A successor router/provider contract is still required to represent governed
remote routes for public and internal data. Confidential and restricted data
must remain local-private-only. This candidate does not execute such a route
and does not claim Phase 6 completion.

The external-agent descriptor remains explicitly `BLOCKED_BY_ACCESS`; it is
discoverable metadata, not an installed provider or executor.

