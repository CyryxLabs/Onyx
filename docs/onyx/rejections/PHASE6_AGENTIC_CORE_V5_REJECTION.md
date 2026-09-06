# Phase 6 Agentic Core V5 rejection record

Status: **REJECTED — preserved byte-for-byte; never accepted or activated**

Date: 2026-07-23

The independent gate rejected V5. Its core, tests, ADR, checkpoint and manifest
remain frozen exactly as reviewed. This additive record is not part of the V5
artifact root.

## Blocking finding

V5's lexical state machine correctly preserved quoted/comment content, but its
outside-state classification used Unicode `isspace()`, `isalpha()`, `isalnum()`
and `lower()`. Those operations accept or case-map non-ASCII code points that
SQLite does not necessarily treat as equivalent ASCII SQL formatting/tokens.
For example, Kelvin sign `K`, NBSP and confusable identifier characters could
be erased or normalized during signature construction.

## Disposition

- V5 remains strict default-off and must not be wired live.
- Its quote/comment states, full PRAGMA inventory and all frozen V4 closures
  remain useful evidence.
- V6 changes only outside-state classification: proven ASCII whitespace,
  explicit ASCII token classes and A-Z byte lowering. Every non-ASCII code
  point remains exact.
