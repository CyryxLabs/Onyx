# Phase 8 Microsoft Graph OneDrive Read V1 checkpoint

This exactly default-off candidate adds the read-only OneDrive/Office vertical
slice: delegated `Files.Read` token acquisition from the native-vault refresh
token, route-pinned GET listing of the drive root, a folder's children and a
single item's metadata, bounded same-origin `@odata.nextLink` paging, and
normalized `DriveItemV1` records. It is metadata-only — no content download, no
upload, rename, move, delete or share.

Eighteen focused tests cover exact gating, accepted-Tasks entry binding, sealed
factory construction, file/folder normalization, list-children and get-item
routes, same-route bounded nextLink paging, cross-route nextLink denial (path,
host, scheme and fragment branches), page-count and item-count paging bounds
(`MAX_PAGES`/`MAX_ITEMS`), get-item collection-shape rejection, missing read
scope, invalid item id rejection before network, provider shape-drift denial
(size, childCount, folder/file facet type, folder+file conflict, missing/empty
identity, non-dict item, NUL text and timestamp drift), access-token caching,
post-expiry token refetch, best-effort refresh rotation tolerating a vault
write failure, route pinning of the drive client (including `/content` denial)
and source-invariant scanning.

The cumulative selection contains 421 passing tests and 80 passing subtests
across twenty fresh processes, with eight inherited and explained
platform-specific skips and zero failure/error.

Limits: the Entra registration must carry delegated `Files.Read` consent, so
live listing E2E is pending and requires an explicitly confirmed run. Metadata
only; no content bytes, SharePoint enumeration, upload/rename/move/delete/share,
runtime wiring, Phase 8 aggregate exit or full PRD completion is claimed.
