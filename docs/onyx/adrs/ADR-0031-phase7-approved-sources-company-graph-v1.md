# ADR-0031 — Phase 7 approved sources and Company Graph V1

- Status: candidate
- Date: 2026-07-23
- Depends on: accepted Workspace Memory V1 and Workspace Aliases V1

## Context

Onyx needs a company knowledge surface that distinguishes known facts,
proposals, rejected and superseded decisions, hypotheses, risks,
dependencies, metrics and evidence. A file, model response or agent statement
must never become authority by itself. Every operational status needs an
owner, verification time, confidence, blockers, next milestone, definition of
done and source-grounded evidence.

The existing Domain Ledger already provides immutable, workspace-scoped
evidence and claim records. Workspace Aliases provide content-free artifact
identities. Neither defines which company sources are approved nor projects a
read-only business graph.

## Decision

Add two exactly default-off components:

1. `ApprovedSourceRegistryV1` admits immutable, HMAC-authenticated source
   policy records into the existing `capability_descriptors` table. Each
   source is bound to one workspace and principal and records source type,
   authority, rights, sensitivity, canonical locator/citation, diversity
   group, eight basis-point quality scores, validity and freshness.
2. `CompanyGraphProjectorV1` joins caller-supplied typed graph assertions to
   exact Domain Ledger claims/evidence and approved-source records. It returns
   a deterministic, content-addressed, read-only projection and writes
   nothing.

Source content is always `untrusted_data` and never has instruction authority.
HTTPS locators are metadata only and are never fetched. Artifact sources
re-attest an accepted artifact alias but never read bytes. Source sensitivity,
lifecycle and freshness are checked before evidence lookup.

The graph refuses hidden contradictions or supersessions. Known semantics
require supported claims. A `verified_complete` status additionally requires a
supported current-status claim, nonempty DoD, no blockers and an authoritative
test report, release or formal decision record. An artifact merely existing is
insufficient.

The projection digest covers every returned operational, provenance,
relationship, freshness and trust field.

## Consequences

- Revoked, stale, expired, tampered, cross-workspace, cross-principal or
  source/evidence-drifted records fail closed.
- Prompt injection inside source excerpts remains inert untrusted evidence.
- The existing memory, alias, ledger, model, voice, UI and live V13 engines are
  unchanged.
- This slice supplies the source/graph foundation but not automated
  contradiction discovery, portfolio freshness alerts, Founder Brief or live
  command routing.

## Rollback

Leave `ONYX_PHASE7_APPROVED_SOURCES_V1` and
`ONYX_PHASE7_COMPANY_GRAPH_V1` unset. Neither component is constructed.
Previously written source descriptors remain inert and auditable; the graph
has no persisted projection to roll back.
