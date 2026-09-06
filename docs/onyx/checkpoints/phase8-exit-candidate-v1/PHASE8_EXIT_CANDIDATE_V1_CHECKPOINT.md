# Phase 8 exit candidate V1 checkpoint

This aggregate, verification-only checkpoint binds the seven independently
E6-accepted Phase 8 Microsoft Graph executive-office slices — OAuth V1, Read V1,
Live Read E2E V1, Calendar V1, Mail V1, Tasks V1 and OneDrive Read V1 — to the
Phase 8 PRD connector requirements. It adds no code module, feature flag or
runtime wiring.

The coverage map pins each accepted slice by its four-file acceptance tuple
(candidate manifest, acceptance record, acceptance metadata and SHA anchor),
for twenty-eight accepted-component-root files across seven slices, and maps
each Phase 8 connector requirement (delegated least-scope OAuth, route-pinned
read/brief/paging, a contract-proven live-read E2E slice, calendar availability
plus one exact-grant create, exact-recipient content-bound mail draft/send,
deterministic notification routing plus one exact-grant To Do create, and
route-pinned metadata-only OneDrive read) to its satisfying `VE-*` evidence. The
verifier machine-checks that mapping: every accepted slice has exactly one
requirement citing exactly its accepted identifier.

The cumulative selection reproduces 421 passing tests and 80 passing subtests
across twenty fresh Python processes — the seven inherited Phase 7 stable-core
files, five shared control-plane/registry/memory/ledger/artifact files and the
eight Phase 8 test files — with eight inherited, explained platform-specific
skips and zero failure/error. Twenty test files but seven accepted slices: the
eighth Phase 8 test file, `test_phase8_microsoft_graph_device_bootstrap_v2.py`,
exercises a development corrective (device-code sign-in that primes the native
vault); it has no E6 acceptance envelope and is deliberately excluded from the
accepted component roots while remaining in the gate.

Scope and limits: this is the **default-off connector contract layer only**.
Every claim binds exactly the seven accepted E6 envelopes, each of which is
route-pinned, default-off contract evidence. No live execution is bound or
claimed here — no live read, calendar create, mail send, task create or drive
listing is part of this aggregate's evidence, and the frozen acceptance records
it pins each report their own live E2E as pending owner consent plus a confirmed
run. (A live read and one live calendar create were exercised during development
and written as unbound runtime reports under `runtime/phase8-*-e2e/`, explicitly
outside this aggregate's bound scope.) The aggregate does not cover the PRD's
daily-operations behaviours (inbox triage, deadlines/follow-ups, prep,
travel-aware scheduling, task/review cadence, meeting decision/action
reconciliation), and claims no startup/voice/UI/dashboard wiring, no Phase 9–16
work and no full Onyx PRD completion.
