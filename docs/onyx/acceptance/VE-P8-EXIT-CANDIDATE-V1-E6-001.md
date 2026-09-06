# Phase 8 Exit Candidate V1 — E6 acceptance

- Evidence ID: `VE-P8-EXIT-CANDIDATE-V1-E6-001`
- Decision date: `2026-07-24`
- Decision: **ACCEPTED — Phase 8 connector-layer default-off implementation exit**
- Candidate manifest: `8b23754d1d0cbc6f5ec613a5b454ed66cb933cd007fb0c4524f8d92cd8bdfd46`
- Artifact root: `114cba2de27b680848ed5bfe6ddba7e0033c6448d6f85d198689aa8cffc1485a`

Final findings are `P0=0`, `P1=0`, `P2=0` and `P3=0`. Each Phase 8 connector
requirement maps to one of seven independently E6-accepted Microsoft Graph
slices — OAuth V1, Read V1, Live Read E2E V1, Calendar V1, Mail V1, Tasks V1 and
OneDrive Read V1 — pinned by twenty-eight immutable accepted-component-root
files (seven four-file acceptance tuples). The aggregate verifier reproduced
**421 passed tests, 80 passed subtests, 0 failed and 0 errors** in twenty fresh
Python processes; eight skips are inherited, documented platform-specific
Phase 7 contracts.

The three independent reviews ran adversarially. Integrity returned PASS first
pass: the artifact root and all twenty-eight accepted roots recompute exactly,
two spot-checked slice acceptances still return `accepted` with matching roots,
no accepted predecessor was modified, and the gate reproduces from scratch.
Functional returned PASS-WITH-CONCERNS with a P1 — the checkpoint and ADR
originally carved out "one proven live run" as though a live calendar/read E2E
were part of the bound evidence, which it is not — plus P2/P3 items (the
requirement→evidence mapping was unenforced narrative; some claim flags were
unguarded; no per-file sum check). Quality returned PASS-WITH-CONCERNS with a
scope-ambiguous completion boolean, the same unenforced-mapping observation, an
unexplained twenty-test-file vs seven-slice gap, and an "office" over-label on
the drive requirement key.

All findings were remediated before acceptance. The aggregate was rescoped to
the **default-off connector contract layer only**: every live-run assertion was
removed from the ADR, checkpoint and coverage claims (a development live read
and one live calendar create remain as unbound runtime reports under
`runtime/phase8-*-e2e/`, explicitly outside this aggregate's bound scope); the
completion boolean was renamed
`phase8_connector_layer_default_off_implementation_complete`; the drive
requirement key was narrowed to `drive_metadata_read`; the verifier now
machine-enforces the requirement→evidence mapping (each requirement cites exactly
its slice's accepted identifier and every accepted slice has one requirement),
guards the `live_e2e_bound_in_aggregate`, `phase9_started` and
`one_provider_proven_before_generalizing` flags, and cross-checks the per-file
test-count sum against the aggregate; and the checkpoint now explains that the
eighth Phase 8 test file (`device_bootstrap_v2`) is a development corrective with
no E6 envelope, deliberately excluded from the accepted roots while remaining in
the gate. The residual self-anchoring of a candidate manifest is inherent to the
E1–E5 stage and is externally anchored by this very acceptance record, exactly
as for the accepted Phase 5, 6 and 7 exits.

Phase 8 is accepted for connector-layer default-off implementation completion;
Phase 9 may begin. This acceptance binds no live execution: live read, calendar
create, mail send, task create and drive listing each still require delegated
consent plus an explicitly confirmed run and are not part of the bound evidence.
It covers no PRD daily-operations behaviours (inbox triage, deadlines/
follow-ups, prep, travel-aware scheduling, task/review cadence, meeting
decision/action reconciliation), live-wires no component, adds no action
authority and does not claim the full Onyx PRD complete.
