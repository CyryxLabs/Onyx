# Phase 7 Workspace Aliases V1 — E6 acceptance

- Evidence ID: `VE-P7-WORKSPACE-ALIASES-V1-E6-001`
- Decision date: `2026-07-23`
- Decision: **ACCEPTED — default-off typed workspace aliases**
- Candidate manifest:
  `ec1938f4b1671187ed8384f104bb6082b0bd75d157cf4c8f12e259beb5612ca4`
- Artifact root:
  `1ae29f0e8300b19737f61e795ea867f474d5dc7efd803a5a6bbaef4e74f2362e`

## Decision

Workspace Aliases V1 is accepted as the second ordered Phase 7 slice.
Findings are `P0=0`, `P1=0`, `P2=0`, and `P3=0`.

The independent gate:

- rehashed all seven candidate artifacts and recomputed the artifact root;
- rehashed and interpreted the accepted Workspace Memory V1 entry envelope;
- reproduced exact default-off return-before-entry validation;
- executed the alias, control-plane, workspace, security, audit, artifact and
  credential suites in fresh Python processes;
- reproduced **160 passed tests, 113 passed subtests, 0 failed, 0 errors**;
- reproduced nine explained Windows platform skips for POSIX-only contracts;
- confirmed no secret read/storage, browser launch, artifact-content read,
  network/process/provider/live call or startup seam.

## Accepted behavior

The accepted catalog:

- binds every alias to one active non-legacy workspace, one principal, one
  initialized control-plane connection and one host integrity key;
- stores canonical HMAC-authenticated credential/profile/artifact locator
  metadata in the additive `capability_descriptors` table;
- uses versioned workspace/provider-specific OS-vault service/account names
  without resolving credential values;
- uses logical workspace browser profile locators and exact allowed domains
  without exposing filesystem profiles, cookies or password stores;
- requires and reattests an exact available authoritative `artifact_index`
  row before returning an artifact alias;
- provides immutable idempotent create, bounded typed reads and persistent
  non-resurrecting revoke.

## Limits retained

- V1 remains default-off and is not wired to V13, startup, voice, UI or the
  dashboard.
- It does not resolve secrets, launch browsers, open profile content or read
  artifact bytes.
- Approved-source registry, Company Graph, contradiction/freshness and Founder
  Brief remain unimplemented.
- Phase 7 is not exited and the full Onyx PRD is incomplete.

The next slice may implement the approved-source registry over the accepted
workspace memory and alias boundaries without weakening isolation.
