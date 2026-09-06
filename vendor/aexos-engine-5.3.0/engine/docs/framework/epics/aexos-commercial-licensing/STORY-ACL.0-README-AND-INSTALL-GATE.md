# Story ACL.0: Commercial README and pre-install entitlement gate

| Field    | Value                                                                            |
| -------- | -------------------------------------------------------------------------------- |
| Story ID | ACL.0                                                                            |
| Epic     | AEXOS Paid-Only Commercial Licensing                                             |
| Status   | Ready for Review                                                                 |
| Scope    | Local candidate foundation; no release, payment charge or legal-term replacement |

## User story

As the AEXOS product owner, I want the public repository to explain the product accurately and the
licensed release candidate to validate an entitlement before writing product files, so that the
commercial transition is credible without misrepresenting the already-published free artifact or
creating a destructive lockout.

## Acceptance criteria

- [x] README uses the official AEXOS website lockup and product captures as its primary visual
      narrative; one real Virtual Office capture remains secondary to the CLI product.
- [x] README installation commands use the canonical repository and published package names.
- [x] README removes stale hard-coded test totals and reports reproducible agent/team counts.
- [x] README distinguishes the current `5.3.0` licence from the future paid-only candidate.
- [x] The installer has one pre-install commercial entitlement boundary that runs before framework
      or squad files are written when the packaged release mode is `enforce`.
- [x] The enforced path has no Community/free fallback and returns a typed, actionable failure.
- [x] The current historical package mode remains non-enforcing until an exact paid-only release
      candidate is approved; no environment variable can turn a production denial into authority.
- [x] Focused tests prove enforcement ordering, successful admission, non-enforcing historical mode
      and secret-safe errors.
- [x] `npm run lint`, `npm run typecheck`, `npm test` and `npm run build` pass before completion.

## Constraints

- Payment processing and entitlement issuance remain server-side and outside this repository.
- The public repository cannot provide strong anti-copy protection; the paid engine must be
  delivered as an authenticated private artifact.
- No existing release is retroactively relicensed.
- License failure never deletes, encrypts or withholds export of user-owned project data.
- No commit, push, release, deployment, repository visibility change or customer charge is
  authorized by this story.

## File list

- [x] `README.md`
- [x] `.github/assets/readme/aexos-official-lockup.png`
- [x] `.github/assets/readme/website-hero.png`
- [x] `.github/assets/readme/website-architecture.png`
- [x] `.github/assets/readme/website-workflows.png`
- [x] `.github/assets/readme/virtual-office-overview.png`
- [x] `docs/framework/epics/aexos-commercial-licensing/STORY-ACL.0-README-AND-INSTALL-GATE.md`
- [x] `packages/installer/src/licensing/commercial-license-gate.js`
- [x] `packages/installer/src/wizard/index.js`
- [x] `tests/installer/commercial-license-gate.test.js`
- [x] `package.json`

## External release gates

- Replacement commercial licence reviewed by qualified counsel.
- Payment provider webhook and idempotent entitlement issuance proven in the license-server.
- Production signing key, public-key rotation and revocation ownership approved.
- Authenticated artifact storage and rollback proven for the exact candidate.
- Independent QA PASS and DevOps release approval.

## Validation evidence

- `npm run lint`: PASS.
- `npm run typecheck`: PASS.
- `npm test -- --runInBand`: PASS — 397 suites passed, 12 skipped; 9,906 tests passed,
  172 skipped; zero failures.
- `npm run build`: PASS — publish safety gate passed with 3,524 packaged files and verified
  exclusion of `pro/` content.
- `node scripts/validate-squads.js`: PASS — 20 squads, zero errors and zero warnings.
