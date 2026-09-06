# ADR-0030 — Phase 7 workspace aliases V1

- Status: candidate
- Date: 2026-07-23
- Depends on: accepted Workspace Memory V1

## Context

Phase 7 requires credential, browser-profile and artifact identities to remain
inside the selected workspace. Existing credential, browser and artifact
engines must remain intact, and no alias store may become a second secret
vault, cookie database or artifact-content store.

## Decision

Add an exactly default-off `WorkspaceAliasCatalogV1` over the existing
`capability_descriptors` table. The catalog is sealed to one active,
non-legacy workspace, one principal, one initialized control-plane connection
and a 32–64 byte host integrity key.

The catalog supports immutable create/read/list and persistent revoke:

- a credential alias stores provider, account/tenant identity, scopes,
  rotation/revoke deadlines and versioned OS-vault service/account locators;
- a profile alias stores a workspace/browser/profile logical locator and exact
  allowed domains, never a filesystem path, cookie or password-store location;
- an artifact alias stores a locator and the exact authoritative
  `artifact_index` identity, digest, canonical relative path, media type,
  schema version and creation timestamp.

Every payload is canonical JSON authenticated with HMAC-SHA256. Alias identity
includes schema, workspace, principal, kind and name. Credential deadlines
fail closed. Artifact bindings are checked under the write transaction and
again on every read. Revocation changes lifecycle metadata but never deletes
history or resurrects an identity.

The module does not import or call the credential resolver, browser engine,
artifact content reader, network, process, model, voice, UI or live runtime.
It adds no startup flag or runtime seam.

## Consequences

- Cross-workspace and cross-principal lookup returns no locator.
- Secret-like supplied values, noncanonical paths/domains/JSON, forged HMAC,
  artifact drift and inactive-workspace drift deny.
- The existing control-plane schema and engines remain unchanged.
- The catalog is a prerequisite, not completion, of approved sources, Company
  Graph, Founder Brief, live credential resolution or workspace browser launch.

## Rollback

Leave `ONYX_PHASE7_WORKSPACE_ALIASES_V1` unset. No catalog is constructed and
the existing credential, browser, artifact, voice and UI behavior is unchanged.
Previously written signed descriptors remain auditable and inert.
