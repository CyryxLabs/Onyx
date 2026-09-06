# EPIC — AEXOS Paid-Only Commercial Licensing

**Status:** Draft — not Ready for implementation
**Goal:** Replace the Core/Pro split with one paid, entitlement-controlled AEXOS
product without retroactive relicensing, destructive lockout or a public
production bypass.

## Dependencies

- Founder approval of the direction: recorded.
- Commercial parameters listed in `CHANGE-PROPOSAL.md`: pending.
- Replacement license legal review: pending external gate.
- Production license authority and authenticated distribution ownership:
  pending.

## Delivery waves

| Wave | Proposed story scope                                                                   | Primary executor         | Gate                          | State                                           |
| ---- | -------------------------------------------------------------------------------------- | ------------------------ | ----------------------------- | ----------------------------------------------- |
| 0    | Legal/product terms, historical-version transition and canonical entitlement contract  | `@pm` + external counsel | `@architect` / founder        | Draft                                           |
| 1    | Real signed entitlement library, cache, machine/seat policy and deterministic fixtures | `@dev`                   | `@architect`, `@qa`           | Blocked by Wave 0                               |
| 2    | License API, payment-event idempotency, revocation and authenticated artifact contract | `@dev`                   | `@architect`, `@qa`, security | Blocked by Wave 0                               |
| 3    | Canonical CLI/runtime enforcement and recovery allowlist                               | `@dev`                   | `@architect`, `@qa`           | Blocked by Waves 1–2                            |
| 4    | Installer migration, old-Core detection, explicit acceptance and rollback              | `@dev`                   | `@qa`                         | Blocked by Wave 3                               |
| 5    | Remove Community/Core-free surfaces and converge Core/Pro packaging                    | `@dev`                   | `@qa`, legal scan             | Blocked by Wave 4                               |
| 6    | Cerberus entitlement mapping and worker-start enforcement                              | `@dev`                   | `@architect`, `@qa`           | Blocked by Knowledge story readiness and Wave 3 |
| 7    | Cross-platform same-artifact commercial RC, security and recovery certification        | `@devops`                | `@qa`                         | Blocked by Waves 1–6                            |

Detailed story creation belongs to `@sm` after Wave 0 decisions are approved.

## Epic acceptance criteria

1. Every production entrypoint resolves the canonical entitlement state before
   executing AEXOS capabilities.
2. No Community, free-production or no-fee Core grant appears in the new
   candidate package or current-facing documentation.
3. No historical copy is represented as retroactively relicensed.
4. The production package contains no scaffolded licensing implementation.
5. Invalid entitlement states expose only the documented recovery allowlist.
6. License failure never deletes, encrypts, corrupts or withholds export of
   user-owned project data.
7. Offline, grace, expiry, revocation, refund, chargeback, seat conflict,
   recovery and uninstall cases are deterministic and tested.
8. Internal development and CI use signed, auditable entitlements with no
   production bypass.
9. Cerberus capabilities are authorized by AEXOS before worker launch and no
   knowledge content reaches the license service.
10. Windows, Linux and macOS install the same signed candidate through the
    authenticated distribution path.
11. `npm run lint`, `npm run typecheck` and `npm test` pass for every
    implementation story, plus focused security and package gates.
12. Qualified legal review, independent QA PASS and DevOps release approval are
    recorded for the exact artifact before external distribution.

## Negative scope

- No license, billing endpoint or payment provider is invented in this epic.
- No current user is locked out during planning or shadow-validation waves.
- No package is unpublished and no repository visibility is changed here.
- No commit, push, tag, publish or deployment is authorized by this document.

## Definition of Done

- All waves completed with their gates.
- Commercial parameters and replacement license approved.
- Production licensing contains no stubs.
- Paid-only candidate passes entitlement, security, migration, recovery,
  Cerberus and cross-platform matrices.
- Exact-candidate QA verdict is PASS and DevOps approves the release
  transaction.
