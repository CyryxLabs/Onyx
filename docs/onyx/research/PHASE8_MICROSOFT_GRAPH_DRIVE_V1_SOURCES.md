# Phase 8 Microsoft Graph OneDrive Read V1 — Official Sources

Drive listing/metadata and permission pages verified against Microsoft Learn
for this candidate on 2026-07-24; throttling and refresh-token pages were
re-verified on 2026-07-23 for the accepted live-read predecessor and are
unchanged.

## Drive listing and item metadata

- [List children of a driveItem](https://learn.microsoft.com/en-us/graph/api/driveitem-list-children?view=graph-rest-1.0)
  defines `GET /me/drive/root/children` and
  `GET /me/drive/items/{item-id}/children`, returning a `value` collection of
  `driveItem` objects with `@odata.nextLink` paging. Delegated permission:
  `Files.Read`.
- [Get a driveItem](https://learn.microsoft.com/en-us/graph/api/driveitem-get?view=graph-rest-1.0)
  defines `GET /me/drive/items/{item-id}` returning a single item with `id`,
  `name`, `size`, the `folder`/`file` facets, `lastModifiedDateTime` and
  `webUrl`.
- [driveItem resource type](https://learn.microsoft.com/en-us/graph/api/resources/driveitem?view=graph-rest-1.0)
  documents `folder.childCount`, the `file` facet and the metadata fields V1
  normalizes.

## Permissions and least privilege

- [Microsoft Graph permissions reference](https://learn.microsoft.com/en-us/graph/permissions-reference)
  distinguishes `Files.Read` from `Files.ReadWrite`. V1 requests exactly
  `Files.Read`, `User.Read`, `offline_access` and validates the granted
  `Files.Read` scope before listing, denying if absent.

## Content download (deliberately deferred)

- [Download the contents of a driveItem](https://learn.microsoft.com/en-us/graph/api/driveitem-get-content?view=graph-rest-1.0)
  documents `GET /me/drive/items/{item-id}/content` returning a `302` redirect
  to a pre-authenticated download URL. Because the V1 client disables redirects
  and pins the Graph origin, content download is out of scope for this
  metadata-only slice and belongs to a later gated successor.

## Throttling (inherited)

- [Microsoft Graph throttling guidance](https://learn.microsoft.com/en-us/graph/throttling)
  applies to the read GETs; V1 surfaces provider errors without automatic
  retry.

## Local limitations

- The Entra registration must carry delegated `Files.Read` with consent; live
  listing E2E is pending that consent plus an explicitly confirmed run.
- Metadata listing only; no content bytes, no SharePoint document library
  enumeration, no upload/rename/move/delete/share.
