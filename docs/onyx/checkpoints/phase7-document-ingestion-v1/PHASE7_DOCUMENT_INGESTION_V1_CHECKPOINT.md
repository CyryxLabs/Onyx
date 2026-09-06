# Phase 7 Document Ingestion V1 checkpoint

The default-off read-only candidate implements PDF, DOCX, Markdown/text,
spreadsheet, presentation, image/OCR and code ingestion with granular
citations, version comparison, deterministic requirement/decision extraction,
local PDF/image rendering and hash-bound visual observations.

Seventeen focused tests cover every required format, citations, grounding,
OCR bbox, visual QA, version deltas, injection inertness, source revocation,
result tamper, workspace scope, zero persistence and archive/XML defenses.
The cumulative selection contains 178 tests and 77 subtests in ten fresh
processes with zero failure/error and one explained POSIX-only skip.

Limits: candidate is not live-wired; it returns candidate memory specs but
does not persist them. OCR observations come from the existing governed vision
path. Phase 7 aggregate exit remains pending.
