# ADR-0010: Add a default-off agentic planning facade over MissionStore

- Status: Candidate implemented; not accepted or activated
- Date: 2026-07-22
- Decision owners: Cyryx Labs / Onyx owner

## Context

Onyx already has one durable execution authority in `core/missions.py`, one
mission-tool policy in `core/permission_broker.py` and provider-free read tools
in `core/mission_tools.py`. Phase 6 needs provider-neutral planning, operator
assignment, verification, repair and model/external-agent ports without creating
a second queue, dispatcher or approval system.

## Decision

Add `core/phase6_agentic_core_v1.py` as an isolated facade with the strict
`ONYX_PHASE6_AGENTIC_CORE_V1=true` gate and an explicit host-owned workspace
scope. The facade may persist typed Goal/Plan/Step metadata, projections,
append-only event evidence and verification receipts in its own SQLite sidecar,
but it cannot claim or execute work. Executable provider-free plans are compiled
once into the existing `MissionStore`; that mission remains execution truth.

V1 admits only the existing provider-free read-only mission tools and can plan
`local_catalog_read`. The catalog operation remains owned by accepted Phase 5
and therefore stops in `waiting_for_phase5` until a separately reviewed adapter
binds the exact Phase 5 identity/authorization/dispatch contract. Model routing
uses hard workspace, privacy, modality, availability, reliability, latency and
cost filters. The only invocable planner adapter is deterministic and local;
provider adapters and `ExternalAgentAdapterV1` are declarations/interfaces only.

The independent verifier reopens MissionStore's public plan, authority snapshot
and hash-chained events, compares the exact materialized plan and expected
postconditions, and writes content-digested receipts. Bounded repair creates a
new immutable plan; it never edits a running or completed mission. Cancel and
the persistent one-way kill latch delegate late-result rejection to
MissionStore. Restart recovery reconciles projections but never auto-replays a
step.

## Consequences and limits

- Existing voice, Gemini Live, local/text LLM, UI, permission, Phase 5 and live
  configuration files are unchanged.
- V1 does not turn free-form natural language into a plan through a model. A
  host must supply typed candidate steps, which remain untrusted until validated.
- Existing `core/llm_client.py` and Gemini Live compatibility adapters still need
  separate modality-specific implementation and parity evidence.
- Existing memory remains unchanged and is not yet injected into planner context;
  a later adapter must preserve workspace filtering and the compatibility API.
- No external coding agent, subprocess or provider is started. The external
  adapter truthfully returns `BLOCKED_BY_ACCESS`.
- Step timeouts discard late provider-free results, but Python cannot forcibly
  terminate the daemon calculation; admitted V1 tools are already bounded and
  read-only.
- The Phase 6 SQLite controls are application-integrity controls, not a privilege
  boundary against arbitrary same-process/same-user code. Reopen rejects missing
  schema triggers; a future operational integration should bind evidence to the
  accepted ledger rather than promote this sidecar to execution authority.

## Rollback

Leave the feature flag false or remove the isolated module and sidecar after an
authorized export. No live database, mission schema, permission policy, provider,
startup path or UI requires restoration.

## Verification gate

Acceptance requires independent functional, integrity and quality review of the
frozen checkpoint, plus closure or explicit baseline classification of the
unrelated `OnyxLive.__new__` regression recorded in the checkpoint. This ADR does
not satisfy Phase 6 E6 and does not authorize live wiring.
