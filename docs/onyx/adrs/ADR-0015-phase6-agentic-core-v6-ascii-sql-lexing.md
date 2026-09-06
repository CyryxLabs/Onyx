# ADR-0015: Phase 6 V6 SQLite-relevant ASCII lexing

Status: Candidate — default-off, not accepted, not live

Date: 2026-07-23

## Context

V5 correctly separated quoted and comment states, but outside those states it
used Unicode character classification and case mapping. Unicode whitespace and
compatibility case mappings are broader than the SQLite formatting equivalence
V5 had actually proved. A signature must not make Kelvin sign `K`, NBSP or
confusable identifiers equivalent to ASCII tokens.

V1-V5 remain frozen. V6 changes only outside-state token classification and
reapplies the corrected signature to coordination and the exact-input ledger.

## Decision

### Explicit ASCII classes

V6 recognizes exactly five outside-state whitespace bytes: space, tab, CR, LF
and form feed. It recognizes identifiers and numbers through explicit ASCII
sets. Only bytes `A` through `Z` are mapped to `a` through `z`; no Unicode
`isspace`, `isalpha`, `isalnum`, `lower` or `casefold` operation is used.

Every non-ASCII code point is emitted as its own exact token outside literals
and comments. Vertical tab is also exact rather than whitespace because it was
not part of the proven SQLite equivalence set.

V5's lexical states remain intact: single/double/backtick/bracket quoted bytes,
blob payloads, doubled escapes and line/block comments remain exact.

### Authentication evidence

Tests prove:

- ASCII `K`/`k` are equivalent unquoted tokens, while Kelvin `K` is distinct;
- ASCII space is distinct from NBSP and vertical tab;
- Greek, Cyrillic, fullwidth and sharp-S confusables are never folded;
- non-ASCII identifier case remains exact;
- two valid SQLite schemas with the same table/column names but declared types
  `K` and `K` have different complete signatures;
- replacing V6's `REAL` declared type with valid `KEAL` under the same object
  names fails before writes and leaves the database hash unchanged;
- only SP/TAB/CR/LF/FF formatting and ASCII keyword case reopen as the
  explicitly proven benign class.

The full `sqlite_master` token stream and V5/V4 PRAGMA inventories continue to
authenticate both V6 databases.

### Preserved closures

V6 subclasses V5 only after replacing construction and schema authentication.
All V4 process, CAS recovery, fencing, idempotency, lifecycle and compaction
behavior and all V5 quote/comment behavior remain unchanged. An end-to-end V6
test covers plan, materialization, approval, isolated execution, isolated
verification and close.

## Consequences

- Exact `ONYX_PHASE6_AGENTIC_CORE_V6=true` is required; V6 is not live-wired.
- Normalization is deliberately narrower and fail-closed for all unproven
  Unicode formatting or identifier equivalence.
- V1-V5, MissionStore and every accepted/live surface remain unchanged.
- Independent gates must approve the frozen V6 checkpoint before activation.

## Rejected alternatives

- Unicode casefold/lower: rejected because compatibility and locale-independent
  Unicode mappings exceed SQLite ASCII keyword behavior.
- Unicode whitespace classification: rejected because NBSP and other separators
  were not proven SQLite formatting.
- Maintaining a confusable allowlist: rejected because new Unicode code points
  would remain an open-ended bypass class.
- Editing V5 in place: rejected because reviewed bytes must remain exact.
