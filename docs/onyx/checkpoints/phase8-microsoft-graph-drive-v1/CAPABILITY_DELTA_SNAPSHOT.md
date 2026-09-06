# Capability delta — Phase 8 Microsoft Graph OneDrive Read V1

## Added behind one exact default-off flag

- Delegated `Files.Read` access-token acquisition from the vault refresh token
  with exact granted-scope validation and best-effort refresh rotation.
- Route-pinned GET listing: drive root (`/me/drive/root/children`), folder
  children (`/me/drive/items/{id}/children`) and single-item metadata
  (`/me/drive/items/{id}`).
- Bounded same-origin, same-path `@odata.nextLink` paging.
- Normalized `DriveItemV1` records (id, name, size, folder/file, child count,
  last-modified, web URL) with provider shape-drift denial.

## Not added

- Content download (`/items/{id}/content` redirect) — deferred to a later
  gated successor.
- Upload, rename, move, delete, share or any Drive mutation.
- SharePoint document-library enumeration.
- Live listing E2E (requires `Files.Read` consent and a confirmed run).
- Startup, V13, voice, dashboard or UI wiring.
- Phase 8 aggregate exit or full PRD completion.
