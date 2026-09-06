# Phase 6 E1-E5 capability delta snapshot

> **HISTORICAL IMMUTABLE CHECKPOINT — NOT CURRENT RELEASE STATUS.** This
> snapshot remains valid only as point-in-time Phase 6 evidence. Use
> [`CURRENT_RELEASE_STATUS.md`](../../CURRENT_RELEASE_STATUS.md) for the
> authoritative shipped-candidate and open-gate state.

Snapshot date: 2026-07-23  
Aggregate E6 state at snapshot: pending

This immutable checkpoint snapshot records the Phase 6 E1-E5 capability delta.
The live `CAPABILITY_MATRIX.md` retains the same semantic section but remains
editable so a later E6 decision can be recorded without rewriting this
candidate.

| Capability | Before | Candidate after | Exact evidence | Limitation | Owner | Next action |
|---|---|---|---|---|---|---|
| Agentic Core and Phase 5 session integration | `PARTIAL` | `PARTIAL` | `VE-P6-AGENTIC-CORE-V6-E6-001`; `VE-P6-LIVE-INTEGRATION-V2-E6-001`; `VE-P6-LIVE-WIRING-V1-E6-001` | Accepted foundations are session-bound in V13, but the aggregate Phase 6 exit is not accepted | Mission Orchestrator/Security | Reproduce the aggregate closure and obtain independent E6 acceptance |
| Gemini Live compatibility | `WORKING_WITH_LIMITATIONS` | `WORKING_WITH_LIMITATIONS` | `VE-P6-GEMINI-LIVE-COMPAT-C003-E6-001`; `ONYX_V13_LIVE_PROMOTION_2026-07-23.md` | Compatibility acceptance used a fake client; V13 proves only point-in-time real voice/provider operation | Onyx Core/Model Router | Retain the existing live path and recheck availability/device readiness operationally |
| Local/text compatibility | `PARTIAL` | `PARTIAL` | `VE-P6-LOCAL-TEXT-COMPAT-V1-E6-001` | Ollama/OpenAI-compatible parity is accepted in isolation; no remote cross-route or silent fallback is authorized | Model Router | Keep local/private routing fail-closed until a separately reviewed router successor |
| Provider registry and privacy-hard planning | `PARTIAL` | `PARTIAL` | `VE-P6-PROVIDER-REGISTRY-V1-E6-001`; `VE-P6-UNIFIED-ROUTER-V1-C002-E6-001` | Registry/plan metadata is live-composed, but remote Gemini remains blocked by policy in Router V1 | Model Router/Security | Accept the Phase 6 aggregate before adding any provider or cross-route |
| Provider-free Research/Verifier Cells | `NOT_IMPLEMENTED` | `PARTIAL` | `VE-P6-RESEARCH-CELLS-V1-E6-001`; `VE-P6-LIVE-WIRING-V1-E6-001` | Distinct authenticated research/verifier roles exist and are session-bound; no provider-backed execution route is claimed | Mission Orchestrator/Verifier | Obtain aggregate E6, then expose only a governed, receipted command route |
| Local read-only MCP adapter | `NOT_IMPLEMENTED` | `PARTIAL` | `VE-P6-LOCAL-MCP-V1-E6-001`; Local MCP C002 dependency reacceptance; `VE-P6-UNIFIED-ROUTER-V1-C002-E6-001` | Protocol and read-only identity are accepted; V13 opens no MCP process and performs no MCP dispatch | Capability Nexus | Preserve read-only scope and add a separately observed local transport run after aggregate E6 |
| Disabled external-agent descriptor | `BLOCKED_BY_ACCESS` | `BLOCKED_BY_ACCESS` | `VE-P6-DISABLED-EXTERNAL-AGENT-DESCRIPTOR-V1-E6-001` | Descriptor is truthful and live-composed with `authority_granted=false`; no agent is installed, authenticated or dispatched | External Agent Adapter/Cyryx owner | Keep disabled until a permitted installed/authenticated test environment exists |
| Phase 6 live composition | `PARTIAL` | `PARTIAL` | `VE-P6-LIVE-WIRING-V1-E6-001`; frozen Live Wiring V2 candidate; `ONYX_V13_LIVE_PROMOTION_2026-07-23.md` | V13 composes the accepted foundations and metadata-only V2 components, but Live Wiring V2 and this aggregate exit still await independent E6 | Onyx Core/Security | Freeze the Phase 6 Exit Candidate V1 bundle, run proportional regressions and complete E6 |

This snapshot does not accept E6, unlock Phase 7, grant a remote cross-route,
install an external agent, or claim permanent provider availability.
