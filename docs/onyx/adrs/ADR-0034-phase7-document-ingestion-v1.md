# ADR-0034 — Phase 7 Governed Document Ingestion V1

- Status: candidate
- Date: 2026-07-23
- Depends on: accepted Approved Sources + Company Graph V1 and Layered Memory V1

## Decision

Add an exactly default-off, read-only ingestor bound to one accepted source
registry, workspace, principal and HMAC key. It accepts immutable bytes and
supports PDF, DOCX, Markdown, text, CSV/TSV/XLSX/XLS/ODS, PPTX, image/OCR and
code. Every extracted unit receives a source/document/revision-bound citation
with page, line, paragraph, table cell, sheet/cell, slide/shape or OCR bounding
box location.

Requirements and decisions are extracted deterministically and remain
reviewable candidate memory records. No extraction is persisted. Version
comparison links before/after citations. PDF and image rendering is executed
locally; other formats accept exact document-hash-bound render observations.
OCR observations likewise bind engine/version/blocks to the exact image hash.

OOXML containers are bounded and reject traversal, duplicate/encrypted
entries, expansion bombs and active XML declarations. Documents and all
observations remain untrusted evidence with permanently false instruction
authority.

## Consequences

- The Phase 7 format, citation, comparison, extraction and visual-QA contract
  is implemented without changing the existing `file_processor`.
- Revoked/stale/deleted sources invalidate prior ingestion results.
- No URL fetch, model, provider, network, process, browser or action authority
  is added.
- OCR execution continues through an existing governed vision adapter; V1
  consumes its hash-bound observation rather than introducing a second engine.

## Rollback

Leave `ONYX_PHASE7_DOCUMENT_INGESTION_V1` unset. The factory returns before
entry verification and no document bytes are parsed or persisted.
