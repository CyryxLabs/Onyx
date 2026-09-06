# ADR-0043 — Phase 8 Microsoft Graph OneDrive Read V1 (read-only vertical slice)

- Status: candidate
- Date: 2026-07-24
- Depends on: accepted Phase 8 Tasks V1 (and the full Phase 8 chain)

## Decision

Add a read-only OneDrive/Office vertical slice behind exact default-off
`ONYX_PHASE8_MICROSOFT_GRAPH_DRIVE_V1`, strictly per PRD order (read metadata
before any mutation):

1. Acquire a delegated `Files.Read` access token from the native-vault refresh
   token, validating the granted scope exactly and rotating the refresh token
   best-effort (the corrected pattern).
2. Expose route-pinned GET listing: the drive root
   (`GET /me/drive/root/children`), a folder's children
   (`GET /me/drive/items/{id}/children`) and a single item's metadata
   (`GET /me/drive/items/{id}`), returning bounded normalized `DriveItemV1`
   records (id, name, size, folder/file, child count, last-modified, web URL).
3. Bounded, same-origin, same-path `@odata.nextLink` paging only.

## Authority boundary

- Route-pinned transport: drive listing/metadata GET and identity token POST
  only. The `/content` download route, upload, rename, move, delete and share
  routes are structurally unreachable.
- Read-only: no grant, nonce, receipt or mutation machinery; no
  startup/voice/UI/dashboard wiring; frozen predecessors untouched.
- Content bytes are deliberately out of scope for V1: content download
  (`/items/{id}/content`) returns a provider redirect to an external download
  host, which the redirect-disabled client would fail closed; a later slice can
  add bounded text-content read behind its own gate.

## Live dependency

Live listing requires the Entra app to carry delegated `Files.Read` with
consent and an explicitly confirmed run. Until then the capability is
contract-proven only.

## Rollback

Leave the flag unset; the factory returns before entry verification. The module
composes only public frozen contracts and can be deleted standalone.
