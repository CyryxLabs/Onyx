# Phase 10 content draft V1 checkpoint

Fourth Phase 10 (social organic OS) slice: a default-off, deterministic, hermetic
content-draft and provenance contract. It adds one module, one feature flag and
no runtime wiring.

`core/phase10_content_draft_v1.py` (`ONYX_PHASE10_CONTENT_DRAFT_V1`) is
entry-bound to the accepted Phase 10 provider-connector four-file acceptance
tuple. It builds `ContentDraftV1` records (draft id, brand, platform, body,
status, disclosure, assets, claims) and a `ContentDraftSetV1` that enforces asset
provenance (`original`/`licensed`/`authorized`; licensed/authorized require a
`rights_ref`), claim validation (a validated claim cites evidence; an `approved`
draft has every claim validated — the anti-fabrication gate), accessibility
(every image/video asset carries `alt_text`), and a brand/policy review gate
(`approved` requires a positive `PolicyReviewRecordV1`). `published` is not a
representable status and there is no publish/schedule method; `is_ready_for_calendar`
is a readiness predicate only. The module calls no model, opens no network, spawns
no process, persists nothing and takes no action.

The cumulative selection reproduces 607 passing tests and 80 passing subtests
across twenty-seven fresh Python processes — the twenty-six inherited Phase 7
stable-core, Phase 8 connector, Phase 9 intelligence and Phase 10 social test
files plus this slice's thirty-seven adversarial tests — with eight inherited,
explained platform-specific skips and zero failure/error.

Scope and limits: drafting, provenance and policy-gating only. No publishing, no
live provider action, no analytics. Publishing/scheduling and the live provider
run remain later gated slices (`BLOCKED_BY_ACCESS`). The slice claims no
startup/voice/UI/dashboard wiring, no later Phase 10 items and no full Onyx PRD
completion.
