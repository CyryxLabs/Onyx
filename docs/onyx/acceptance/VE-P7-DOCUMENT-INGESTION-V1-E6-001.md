# Phase 7 Document Ingestion V1 — E6 acceptance

- Evidence ID: `VE-P7-DOCUMENT-INGESTION-V1-E6-001`
- Decision date: `2026-07-23`
- Decision: **ACCEPTED — default-off governed document ingestion**
- Candidate manifest: `20efa9f6125d881eab60e4edbd04d103196608cd26875634af06ee47793b8a03`
- Artifact root: `8b7749f3228667eb15e66011129549b569caf9adbdd079a50368ae0967b8a513`

Findings are `P0=0`, `P1=0`, `P2=0`, and `P3=0`. The gate rehashed eight
artifacts and reproduced **178 passed tests, 77 passed subtests, 0 failed and
0 errors** in ten fresh Python processes. One skip is the documented
Windows absence of a POSIX mode assertion.

Accepted scope covers PDF, DOCX, Markdown/text, spreadsheet, presentation,
image/OCR and code; granular citations; cited version comparison;
requirement/decision extraction; PDF/image render QA and hash-bound external
render observations; malicious-container defenses; workspace isolation and
source revocation. All content remains untrusted evidence without instruction
authority. The candidate performs no persistence, URL fetch, model/provider,
network/process/browser/action or live-runtime call.

V1 remains default-off and unwired. OCR observations are supplied by the
existing governed vision path. Phase 7 aggregate exit remains pending and the
full Onyx PRD remains incomplete.
