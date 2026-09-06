# Phase 8 Microsoft Graph OneDrive Read V1 — E6 acceptance

- Evidence ID: `VE-P8-MICROSOFT-GRAPH-DRIVE-V1-E6-001`
- Decision date: `2026-07-24`
- Decision: **ACCEPTED — default-off, route-pinned, metadata-only OneDrive read contract**
- Candidate manifest: `3ad944de2b85de78e343f0cbee0556644218ec7d7039b93efe9daffe774758b5`
- Artifact root: `c79ee2960fdf3c74f4ec33cb693cd328a79bfa5547a8e74d2033603f9f0a6c21`

Final findings are `P0=0`, `P1=0`, `P2=0` and `P3=1` (advisory only). The three
independent reviews (functional, integrity, quality) each ran adversarially.
Integrity returned PASS on the first pass: it recomputed every artifact hash,
reconciled the artifact root to the byte, confirmed the verifier re-runs the
real test suite and exits 0, confirmed no accepted predecessor was edited, and
confirmed the selection counts are honest. Functional returned
PASS-WITH-CONCERNS with two P3 hardening gaps in `_item` provider-shape drift
(a payload carrying both `folder` and `file` facets was classified as a folder
rather than rejected; a payload with a missing/empty `id`/`name` was normalized
to `""` rather than rejected). Quality returned PASS-WITH-CONCERNS with one P2
(the advertised `MAX_PAGES`/`MAX_ITEMS` paging bounds had no regression test)
plus P3 test gaps (get-item collection-shape guard, post-expiry token refetch,
best-effort rotation write-failure tolerance, cross-route nextLink host/scheme/
fragment branches) and a dead `SCHEMA` constant.

All actionable findings were remediated before acceptance: `_item` now rejects a
folder+file facet conflict (`drive facet conflict`) and a missing/empty
identity (`drive item identity drift`) via a required-text guard; the dead
`SCHEMA` constant was removed; and six focused tests were added covering the
page-count bound, the item-count bound, get-item collection-shape rejection,
post-expiry token refetch, rotation write-failure tolerance and the additional
cross-route nextLink branches, with the shape-drift table broadened to the
facet-conflict, missing-identity, non-dict-item, NUL-text and timestamp-drift
cases. The focused suite grew from twelve to eighteen tests. The gate rehashed
eight candidate artifacts and reproduced **421 passed tests, 80 passed
subtests, 0 failed and 0 errors** in twenty fresh Python processes. Eight skips
are the previously accepted platform-specific Phase 7 checks.

The sole remaining P3 is an integrity advisory, not a defect: this slice pins
its integrity to the accepted Tasks V1 acceptance evidence (four hashed files
plus the Tasks manifest root) and re-executes the predecessor test files rather
than byte-hashing the three imported predecessor modules directly in its own
closure. This is the intended transitive chain-of-acceptance model; byte-level
tampering of an imported predecessor that kept its tests green would be caught
by that predecessor's own accepted closure, not by this manifest alone.

Accepted scope: a read-only OneDrive vertical slice that acquires a delegated
`Files.Read` access token from the native-vault refresh token with exact
granted-scope validation (denying if `Files.Read` is absent) and best-effort
refresh rotation; exposes route-pinned GET listing of the drive root
(`/me/drive/root/children`), a folder's children (`/me/drive/items/{id}/children`)
and a single item's metadata (`/me/drive/items/{id}`); performs bounded,
same-origin, same-path `@odata.nextLink` paging (`MAX_PAGES=5`, `MAX_ITEMS=500`);
and returns normalized `DriveItemV1` records with strict provider shape-drift
denial. The HTTPS client disables redirects and pins the Graph origin, so the
`/content` download (a `302` redirect) and every mutation verb are structurally
unreachable.

V1 remains exactly default-off and unwired. It adds no content download, no
upload/rename/move/delete/share, no SharePoint document-library enumeration and
no runtime wiring to startup, V13, voice, UI or the dashboard. Live listing E2E
requires the Entra app to carry delegated `Files.Read` with consent and an
explicitly confirmed run. This slice claims no Phase 8 aggregate exit and no
full Onyx PRD completion.
