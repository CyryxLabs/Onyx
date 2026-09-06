# Phase 10 editorial calendar V1 checkpoint

Second Phase 10 (social organic OS) slice: a default-off, deterministic, hermetic
editorial-calendar and approval-ledger contract. It adds one module, one feature
flag and no runtime wiring.

`core/phase10_editorial_calendar_v1.py` (`ONYX_PHASE10_EDITORIAL_CALENDAR_V1`) is
entry-bound to the accepted Phase 10 brand-passport four-file acceptance tuple.
It plans `PlannedPostV1` records (post id, account, platform, injected-clock
future schedule, status, idempotency key, disclosure flag) and `ApprovalRecordV1`
records, and builds an `EditorialCalendarV1` that enforces authorized-account
targeting, unique post ids and idempotency keys, the fixed
`draft -> pending_approval -> approved -> scheduled` lifecycle, and the rule that
`approved`/`scheduled` require an explicit positive approval. `published` is not
a representable status and there is no publish method; `is_ready_to_publish` is a
readiness predicate only. The module calls no model, opens no network, spawns no
process, persists nothing and takes no action.

The cumulative selection reproduces 538 passing tests and 80 passing subtests
across twenty-five fresh Python processes — the twenty-four inherited Phase 7
stable-core, Phase 8 connector, Phase 9 intelligence and Phase 10 brand-passport
test files plus this slice's thirty-four adversarial tests — with eight
inherited, explained platform-specific skips and zero failure/error.

Scope and limits: planning and approval only. No live provider connection,
publishing, analytics or audience data is part of this slice. The first real
publish per account is a later owner-approved, access-gated slice
(`BLOCKED_BY_ACCESS` until OAuth/app-review plus a test account). The slice claims
no startup/voice/UI/dashboard wiring, no later Phase 10 items and no full Onyx PRD
completion.
