# Phase 5.2 Approval Inbox V4 checkpoint

Status: **candidate — default-off, read-only, external acceptance pending**

V4 supersedes the rejected V1, V2 and V3 candidates without modifying a
historical byte. It is an isolated review projection behind strict
`ONYX_APPROVAL_INBOX_V4`; no startup,
runtime, UI, dashboard, provider, connector, tool, owner-data, or mutation path
imports it.

## Trust and authority boundary

The host explicitly composes and pins one `HostInboxSource` and one exact
concrete monotonic clock. Read APIs accept no source items or authority fields.
This is not claimed to provide secrecy from arbitrary Python code in the same
process: a caller can construct a separate inert projection with caller data,
but that creates no live wiring or authority. Display records and authenticated
tokens are non-authoritative review artifacts. No consumer can execute from
them and V4 exposes no approve, deny, revoke, dispatch, persistence, or write
operation.

Public result constructors always fail. Projection-owned closure factories
re-derive canonical view and item-set digests, decode and HMAC-verify exact
snapshot/cursor payload relations, and bind token/cursor digests into page
digests before creating a result. The construction capability is not exported;
same-process reflection into underscore-prefixed internals remains outside the
boundary and conveys no authority.

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
Source epoch rollback or same-epoch semantic equivocation also permanently
latches projection integrity failure, clears cached views/snapshots, and blocks
old and new cursors even if the host later restores the former content. Only a
new projection after restart can recover.
Refreshing only `captured_at_ms` or `valid_until_ms` in the same source epoch
does not alter the semantic integrity digest or latch failure; content changes
still do.

The pinned source owns a nonblocking bounded semaphore with a declared maximum
of one concurrent callback. Excess calls fail closed. No source callback runs
under the projection lock.

## Exact views, pages and calm batches

The view digest and HMAC token bind snapshot, canonical query/filter/sort,
page size, and the exact ordered visible item IDs. Pagination is stable and
exact. Every item actually returned on a page carries an HMAC review token bound
to its snapshot, view, item digest and complete safe human-review fields. Batch
selection accepts only exact `(item_id, review_token)` pairs previously returned
for that view. Hidden, filtered, unreturned, substituted, cross-view and replayed
items fail closed. Batch previews repeat the complete APPROVAL_POLICY review
fields and manifests bind their review and token digests. High, critical,
always-explicit, and otherwise ineligible items never enter a preview.

Display item, page, view, snapshot and batch digests are computed internally
from canonical contents. Result constructors enforce snapshot/view, total,
page-size, offset, item-set, digest, and cursor relations. All results state
`authority_granted=False`; approval and execution surfaces are unavailable.

## Evidence and historical boundary

The V4 verifier materializes and executes the complete accepted Phase 5.1 R11
verifier recursively, which in turn verifies R1-R10. It also materializes and
executes the frozen V2 verifier, which recursively binds its historical closure,
and the frozen V1 verifier. A transitive R11/R10 or V2 drift therefore fails V4;
the adversarial fixture modifies `core/session_grants_v10.py` in a disposable
materialization and proves rejection.

The live boundary uses an AST local-import walk from `main.py`, `ui.py`,
`scripts/launch_onyx.pyw` and discovered launch/run/start entrypoints. It rejects
direct or successor-indirected reachability to any approval inbox. The broad
source manifest excludes only the exact frozen V1-V4 module paths, so a future
`approval_inbox_vN.py` cannot disappear behind a filename pattern.

The verifier derives the exact `MAX_*` limit set and values from V4 source. It
also independently verifies the current Git HEAD, Python/platform/pytest/Ruff
and static-tool identity, canonical JUnit-derived timestamp, focused raw-log
summary, and exact static-gate claims. Adversarial fixtures change limits, base
commit, environment and timestamp, regenerate both manifest hashes, and still
prove semantic rejection.

- Phase 5.1 R11 remains accepted, byte-exact, default-off and shadow-only.
- Phase 5.2 V1 remains historical and rejected, byte-exact.
- Phase 5.2 V2 remains historical and rejected, byte-exact.
- Phase 5.2 V3 remains historical and rejected, byte-exact.
- V4 remains a default-off candidate pending independent external E6 review.
- No Phase 5 live enablement or later phase is accepted by this checkpoint.
