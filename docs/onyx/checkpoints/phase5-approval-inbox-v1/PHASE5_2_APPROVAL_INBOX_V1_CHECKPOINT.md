# Phase 5.2 approval inbox v1 checkpoint

Status: **candidate — default-off, read-only, external acceptance pending**

This slice adds an isolated session-only approval review projection behind the
strict `ONYX_APPROVAL_INBOX_V1` flag. It is not imported by startup, runtime,
the dashboard, providers, tools, or the accepted Phase 5.1 R11 grant module.

## Included

- A pinned host-owned source callback materializes exact immutable records.
- Disabled mode performs no source callback.
- Records expose the complete safe review fields required by
  `docs/onyx/APPROVAL_POLICY.md` without raw targets, raw payloads, or secrets.
- Canonical versioned snapshots bind principal, session, source epoch/revision,
  timestamps, and every exact item digest.
- Signed opaque cursors bind the snapshot, filter, sort, page size, and offset.
  Source drift, expiry, epoch rollback, audit failure, inactive session, and
  kill state fail closed; pages never mix records from different snapshots.
- Calm-batch preview is a finite canonical manifest of exact item digests and
  idempotency keys. Reordering is canonical; add/remove/substitute changes the
  manifest. High, critical, always-explicit, and otherwise ineligible items
  cannot enter a preview.
- All host callbacks run outside the projection lock. Collections, strings,
  pages, snapshots, tokens, and batches are bounded.

## Explicitly excluded

- No approve, deny, revoke, dispatch, execute, persistence, file, database, or
  owner-data mutation API.
- No startup, UI, dashboard, provider, connector, model, or tool wiring.
- No live authority and no permission callback suppression.
- The grant inspector is deferred as
  `omitted-phase5-2b-no-r11-import`; this slice does not import or activate R11.
- Phase 5.2 external E6 acceptance and every later Phase 5 slice remain pending.

## Evidence boundary

`docs/onyx/VE-SOURCE-P52-APPROVAL-INBOX-V1-001.sha256` points only to the
artifact manifest. The artifact manifest binds this checkpoint, source, tests,
verifier, JUnit/raw/static logs, exact live non-wiring scan, normative closure,
and the separate accepted Phase 5.1 R11 source/artifact/acceptance anchors. The
verifier recursively validates the accepted R11 artifact closure without
changing any R11 byte.

The evidence bundle is self-excluding and declares external acceptance pending.
It is evidence for a candidate implementation only, not a production release or
approval authority.
