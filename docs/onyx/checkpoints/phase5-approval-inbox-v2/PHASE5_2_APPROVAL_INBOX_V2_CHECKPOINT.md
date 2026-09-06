# Phase 5.2 Approval Inbox V2 checkpoint

Status: **candidate — default-off, read-only, external acceptance pending**

V2 supersedes the rejected V1 candidate without modifying a V1 byte. It is an
isolated review projection behind strict `ONYX_APPROVAL_INBOX_V2`; no startup,
runtime, UI, dashboard, provider, connector, tool, owner-data, or mutation path
imports it.

## Trust and authority boundary

The host explicitly composes and pins one `HostInboxSource` and one exact
concrete monotonic clock. Read APIs accept no source items or authority fields.
This is not claimed to provide secrecy from arbitrary Python code in the same
process: a caller can construct a separate inert projection with caller data,
but that creates no live wiring or authority. Display records and authenticated
tokens are non-authoritative review artifacts. No consumer can execute from
them and V2 exposes no approve, deny, revoke, dispatch, persistence, or write
operation.

The callback must return the exact `HostInboxSnapshot` type containing an exact
tuple of exact `HostInboxItem` values. Cardinality is checked before item
traversal. Values are reconstructed field-by-field; arbitrary callback values
are never deep-copied and custom iterators/copy hooks are not invoked. Callback
exceptions are collapsed to a fixed code outside the exception context, with no
raw cause, context, arguments, or representation retained.

## Local validity and bounded concurrency

Source timestamps are display metadata only. The projection records a local
monotonic creation time and fixed local deadline for every review snapshot.
Every page and batch operation checks this deadline. Clock rollback permanently
latches failure, and opening a later snapshot cannot resurrect an older token.

The pinned source owns a nonblocking bounded semaphore with a declared maximum
of one concurrent callback. Excess calls fail closed. No source callback runs
under the projection lock.

## Exact views, pages and calm batches

The view digest and HMAC token bind snapshot, canonical query/filter/sort,
page size, and the exact ordered visible item IDs. Pagination is stable and
exact. A batch token can select only IDs visible in its bound view; hidden or
filtered items fail closed. Batch manifests bind canonical item digests and
idempotency keys. High, critical, always-explicit, and otherwise ineligible
items never enter a preview.

Display item, page, view, snapshot and batch digests are computed internally
from canonical contents. Result constructors enforce snapshot/view, total,
page-size, offset, item-set, digest, and cursor relations. All results state
`authority_granted=False`; approval and execution surfaces are unavailable.

## Evidence and historical boundary

The V2 verifier materializes and executes the complete accepted Phase 5.1 R11
verifier recursively, which in turn verifies R1-R10. It also materializes and
executes the frozen V1 verifier. A transitive R11/R10 drift therefore fails V2;
the adversarial fixture modifies `core/session_grants_v10.py` in a disposable
materialization and proves rejection.

- Phase 5.1 R11 remains accepted, byte-exact, default-off and shadow-only.
- Phase 5.2 V1 remains historical and rejected, byte-exact.
- V2 remains a default-off candidate pending independent external E6 review.
- No Phase 5 live enablement or later phase is accepted by this checkpoint.
