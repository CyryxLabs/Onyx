# Phase 5 Exit Candidate V1 capability-matrix delta

This immutable candidate-local delta intentionally does not mutate the
historical `docs/onyx/CAPABILITY_MATRIX.md` projection used by accepted Phase 5
verification closures. That complete file is an exact candidate manifest
anchor; appended content is rejected and no historical prefix is recovered.

`phase5-exit-candidate-v1` composes the five existing external acceptances
without changing their bytes or widening their scopes:
`VE-P5-RUNTIME-V10-E6-001`, `VE-P51-GRANTS-R11-E6-001`,
`VE-P52-APPROVAL-INBOX-V15-E6-001`,
`VE-P53-CAPABILITY-NEXUS-V32-E6-001` and
`VE-P5-INTEGRATION-V3-E6-001`.

| Capability | Status before | Candidate status | Evidence | Boundary |
|---|---|---|---|---|
| Phase 5 governed runtime composition | `PARTIAL` | `PARTIAL` | `manifest.json` | Local E1-E5 candidate only; external E6 pending |
| Bounded grants | `PARTIAL` | `PARTIAL` | Accepted R11 record, rehashed by candidate gate | Default-off/shadow only |
| Approval Inbox | `PARTIAL` | `PARTIAL` | Accepted V15 record, rehashed by candidate gate | Read-only/non-authority |
| Capability Nexus | `PARTIAL` | `PARTIAL` | Accepted V32 record, rehashed by candidate gate | Descriptor/local-catalog projection only |
| Integration transition | `PARTIAL` | `PARTIAL` | Accepted V3 record and transition verifier | No new activation or authority |
| Startup and packaging closure | `PARTIAL` | `PARTIAL` | Exact candidate manifest inventory | V1-V8/bootstrap/active/rollback/release entrypoints; missing or extra paths fail |

The status intentionally does not advance to `WORKING_AND_VERIFIED`.
Phase 5 remains incomplete until an independent reviewer accepts the exact exit
candidate as E6. This candidate does not unlock Phase 6, activate a feature,
or prove Onyx/master-PRD completion. The default-off rollback is evidence-only
because the candidate adds no executable surface or runtime state.
