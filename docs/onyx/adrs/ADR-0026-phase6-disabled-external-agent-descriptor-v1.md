# ADR-0026 — Phase 6 Disabled External-Agent Descriptor V1

- Status: Candidate accepted for isolated verification
- Date: 2026-07-23
- Scope: descriptor-only external-agent absence projection

## Context

Phase 6 requires an explicit answer when an external-agent capability is not
installed, authenticated, or accepted. Returning an absent record is
ambiguous; constructing a live adapter would exceed the available authority.
The existing Capability Nexus V32 and Provider Registry V1 already define the
canonical `BLOCKED_BY_ACCESS` vocabulary and descriptor shapes.

This decision adds metadata around those accepted contracts without changing
their code, activating a provider, or entering any live surface. It does not
modify Activation, HUD, Unified Router, startup, runtime, packaging, or
launchers.

## Decision

Add `core/phase6_disabled_external_agent_descriptor_v1.py` as an isolated,
factory-only, default-off descriptor catalog.

The exact activation token is:

`ONYX_PHASE6_DISABLED_EXTERNAL_AGENT_DESCRIPTOR_V1=true`

Every other value is disabled. Disabled factory construction returns `None`
before validating identity, key, project root, or accepted component artifacts.
Enabled construction remains local metadata projection only and is not an
installation or activation operation.

The descriptor carries:

- exact adapter, provider, workspace, account, profile, and principal identity;
- descriptor version `v1`;
- health `BLOCKED_BY_ACCESS`;
- access reason `no_accepted_installed_authenticated_adapter`;
- empty required and granted scopes;
- authentication `absent`;
- final cancellation semantics because no session exists;
- authenticated blocked-projection receipt semantics;
- one exact Capability Nexus V32 metadata operation; and
- one exact Provider Registry V1 record whose model descriptor is blocked.

The public descriptor and its payload expose no executable, command, path,
environment, or credential field. The inherited Capability Nexus credential
slot is required by that accepted type and is fixed to `None`; inherited
metadata and required scopes are empty.

## Authority and integrity

Construction is factory-only and the descriptor is immutable after its
attestation. Identity fields accept only bounded canonical identifiers and deny
secret- or privacy-looking values.

The catalog byte-verifies the accepted Capability Nexus V32 and Provider
Registry V1 acceptance artifacts on construction and on every projection. No
mutable Activation V10 artifact is an anchor.

Queries bind the exact identity, descriptor version, descriptor digest,
request identifier, and cancellation state. Exact replay returns the same
projection and receipt objects. Request cancellation is final. Cross-identity,
version, digest, component-root, inherited-type, projection, and receipt drift
fail closed.

Receipts use HMAC-SHA256 with a caller-supplied exact 32-byte key. Receipts
contain only digests and blocked status metadata; they contain no prompt,
message, result content, credential, or provider response.

## Operational boundary

The candidate imports no networking, process, browser, provider SDK, or live
runtime module. It creates no provider registry, router, adapter, session,
process, socket, command, or executable. Provider, process, network, and live
call counters are structurally fixed to zero.

A focused structural scan proves the module and feature flag are absent from
`main.py`, `ui.py`, dashboard, runtime, packaging, QML, and launchers. This is
absence-of-wiring evidence, not a live acceptance claim.

## Consequences

The candidate gives callers a deterministic and authenticated
`BLOCKED_BY_ACCESS` description while preserving the current engine. It does
not make any external agent operational, install credentials, discover an
agent, contact a provider, alter routing, or activate a feature.

Independent E6 acceptance remains a separate future gate.
