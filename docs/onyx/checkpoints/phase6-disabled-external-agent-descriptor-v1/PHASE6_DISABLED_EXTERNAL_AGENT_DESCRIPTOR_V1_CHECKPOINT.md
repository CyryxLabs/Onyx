# Phase 6 Disabled External-Agent Descriptor V1 — Checkpoint

## Candidate

- ID: `phase6-disabled-external-agent-descriptor-candidate-001`
- Feature flag: `ONYX_PHASE6_DISABLED_EXTERNAL_AGENT_DESCRIPTOR_V1`
- Only enabled value: `true`
- Default: off
- Factory-only: yes
- Live wiring: no
- Provider/process/network/live calls: zero
- E6: not performed

## Accepted contract bindings

The candidate uses the exact accepted types from:

- Capability Nexus V32: `CapabilityDescriptorV32`,
  `OperationDescriptorV32`, and `CapabilityStatusV32.BLOCKED_BY_ACCESS`.
- Provider Registry V1: `ProviderRecordV1`, containing the exact
  `ModelDescriptorV1` contract with `AdapterStatusV1.BLOCKED_BY_ACCESS`.

Five accepted component artifacts are byte-bound. They cover the Capability
Nexus V32 bundle and E6 record plus the Provider Registry V1 candidate
manifest, E6 record, and E6 metadata manifest. No Activation, HUD, Router,
startup, or other mutable live artifact is frozen.

## Implemented evidence

- Exact default-off feature gate.
- Disabled factory returns before dependency or key validation.
- Factory-only catalog and descriptor construction.
- Immutable descriptor after construction.
- Typed six-part identity with secret/privacy metadata denial.
- Versioned `BLOCKED_BY_ACCESS` health and explicit access reason.
- Empty required and granted scopes.
- Authentication fixed to absent.
- Final no-session cancellation semantics.
- Authenticated blocked-projection receipt semantics.
- Capability credential alias fixed to `None`; capability metadata empty.
- Provider descriptor blocked by access and workspace-bound.
- No executable, command, path, environment, or credential field on the
  public descriptor or payload.
- HMAC-SHA256 content-free receipts.
- Exact replay returns the same projection and receipt objects.
- Cross-identity, version, digest, type, component-root, projection, and
  receipt drift denial.
- Runtime availability and authority fixed false.
- Provider, process, network, and live call counters fixed zero.
- Provider/process/network/browser SDK-free AST.
- Focused live-surface scan proves absence from startup and live wiring.

## Verification

Focused suite:

`python -B -m pytest -q -p no:cacheprovider tests/test_phase6_disabled_external_agent_descriptor_v1.py`

Independent artifact verifier:

`python -B scripts/verify_phase6_disabled_external_agent_descriptor_v1.py`

The manifest records exact byte sizes, SHA-256 digests, a sorted artifact root,
and the five immutable accepted component anchors. The verifier recomputes all
of them, validates the candidate AST and public field contract, scans focused
live surfaces, and reruns the focused suite.

## Boundary

This is a descriptor candidate only. It does not install, authenticate,
discover, execute, route to, or communicate with an external agent. It does
not alter Capability Nexus, Provider Registry, Unified Router, Activation,
HUD, `main.py`, `ui.py`, runtime, dashboard, packaging, QML, or launchers.
Independent E6 has not been performed.
