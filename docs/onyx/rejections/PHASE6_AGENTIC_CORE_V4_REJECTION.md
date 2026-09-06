# Phase 6 Agentic Core V4 rejection record

Status: **REJECTED — preserved byte-for-byte; never accepted or activated**

Date: 2026-07-22

The independent gate rejected V4. Its core, tests, ADR, checkpoint and manifest
remain frozen exactly as reviewed. This additive record is not part of the V4
artifact root.

## Blocking finding

V4's `_normalize_sql()` collapsed whitespace and lowercased the complete SQL
string. That transformation did not distinguish SQL lexical state, so it could
change bytes inside single-quoted values, blob literals, double/backtick/bracket
quoted identifiers and comments. The resulting schema signature was therefore
not a canonical authentication of the stored SQL definition.

## Disposition

- V4 remains strict default-off and must not be wired live.
- Its expired-only CAS recovery, full PRAGMA inventory, exact materialization
  ledger, terminable process lifecycle, generation fencing and closure evidence
  remain preserved positives.
- V5 replaces only SQL lexical normalization and schema authentication, then
  reuses the remaining frozen V4 behavior through an isolated default-off type.
