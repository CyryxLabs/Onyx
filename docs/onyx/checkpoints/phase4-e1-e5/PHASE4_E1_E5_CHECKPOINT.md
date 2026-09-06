# Phase 4 E1-E5 checkpoint candidate

Evidence ID: `VE-P4-EXIT-CANDIDATE-001`  
Scope binding: accepted isolated/default-off `VE-P44-R10-001`  
Decision state: **candidate only; E6 not performed; activation false**

This package makes the Phase 4 exit decision mechanical without pretending
that fixture evidence is production evidence.  It does not modify a runtime
contract, migrate owner data, enable a flag, import an enhanced service from
startup or make an external call.

## E1 — scope and blockers

Entry conditions are met only for constructing/reviewing this candidate:
Phase 0 artifacts and ADR-0001 through ADR-0005 exist; the project `.venv` is
identified; protected test fixtures exist; and the exact R10 provider-free
slice is accepted with a 77-file immutable manifest.

Included: the already-frozen M1a/M1b/M2a/M2b/MissionContext/P4.4 fixture
implementations, read-only/default-off verification, isolated rollback/failure
tests and this evidence package.  There is no proposed enabled slice.

| Retained blocker/out-of-scope surface | Current status | Required closure evidence |
|---|---|---|
| M1a canonical Windows LocalAppData/token policy | `BLOCKED_BY_PLATFORM` | Re-run under the intended installed-user token; do not weaken owner, DACL or capability checks |
| Owner-store M1b review/backfill | `PARTIAL`, excluded | Explicit owner review plus sanitized source hashes/counts, journal and read-back; never guess a workspace |
| Production startup/owner wiring | excluded | Separate minimal integration, observed runtime and rollback evidence after E6 approval |
| Cross-workspace credential aliases and browser profiles | `PARTIAL`, excluded | Adapter implementation and zero-leak tests |
| Connectors, provider credentials, MCP and provider mutations | `BLOCKED_BY_ACCESS`/`NOT_IMPLEMENTED`, excluded | Authorized test account and health/read/draft/reversible-mutation/reconciliation contract |
| Physical browser/device/LAN behavior | excluded | Host-native/physical-device proportional evidence |
| Proprietary/public release | `BLOCKED_BY_LICENSE`, excluded | Ownership/license closure, locks/SBOM/notices, signing and clean-machine matrix |

E1 candidate result: scope/blockers are explicit; none inherits R10 status or
silently enters an enabled slice.

## E2 — capability delta

The canonical delta is recorded in `CAPABILITY_MATRIX.md` under
"Phase 4 E1-E5 candidate delta."  Every affected status remains unchanged:

| Capability | Before | Candidate after | Owner | Next action |
|---|---|---|---|---|
| M1a canonical Windows activation | `BLOCKED_BY_PLATFORM` | `BLOCKED_BY_PLATFORM` | Onyx Core/Security | Re-run intended-token platform gate |
| Workspace registry/isolation | `PARTIAL` | `PARTIAL` | Onyx Core/Security | Owner review plus shadow dual-read proof |
| Mission context/operational phases | `PARTIAL` | `PARTIAL` | Mission Orchestrator | Prove owner-free integration/rollback before wiring |
| Evidence/claims/actions | `PARTIAL` | `PARTIAL` | Verifier/Security | E6 must choose keep-off or a separately proven narrow activation |

No status is promoted by documentation, code presence or unit evidence.

## E3 — durable verification bundle

Canonical metadata is in `phase4-e1-e5.bundle.json`; raw machine evidence is
`source-gate.json` and `phase4-safety.junit.xml`; file binding is
`VE-SCOPE-P4-E1E5-001.sha256`.  The bundle records:

- base HEAD and branch plus a hash/summary of the dirty worktree observation;
- manifest identity and hashes for R10 and this package;
- exact commands, project interpreter, installed dependency fingerprint,
  platform, timestamp and command durations;
- pass/fail/error/skip counts and hashes of the JUnit/source/static logs;
- limitations: the environment freeze is an observation, not a dependency
  lock, and this proportional gate does not replace accepted R10 or prove a
  release artifact/physical device/provider/runtime integration.

All skips must be explained in the JSON.  Any failure, error, unexplained skip,
manifest mismatch or nonzero static gate blocks E6.

## E4 — safety and rollback

Rollback is the tested no-cutover state:

1. Keep all eight flags in `source-gate.json` unset/false.
2. `main.py`, `ui.py`, `dashboard/server.py` and `dashboard/security.py` import
   no enhanced sidecar/ledger/workspace/mission-evidence module.
3. Disabled V1 initialization raises its typed disabled error and creates no
   isolated owner-like root or database.
4. Existing mission, memory, credential, audit, UI and dashboard paths remain
   authoritative; rollback performs no reverse migration or deletion.
5. Preserve sidecars for diagnosis/export.  Delete only after verified export
   and separate explicit owner authorization.

The proportional gate exercises default-off/no-startup imports, no owner write,
missing/corrupt/unknown sidecars, workspace/mission isolation, cancellation,
restart, unknown-outcome reconciliation/no blind retry and R10 reconstruction.
Negative verifier controls inject static and literal-dynamic startup imports.

Stop/reconcile/revoke:

- **Stop:** do not construct an enhanced service while flags are false.
- **Reconcile:** retain unknown receipts/publications and use only the explicit
  reconciliation path before any retry.
- **Revoke:** Phase 4 has no active grant/connector to revoke.  A future E6
  activation must first detach its integration/descriptor, then disable flag.
- **Incident:** integrity/schema/workspace/audit failure denies enhanced work
  and cannot broaden authority or fabricate mission success.

## E5 — checkpoint package

### Contract and migration inventory

This E1-E5 package adds **0 schema statements, 0 API methods, 0 event types, 0
migration rows and 0 production imports**.  It freezes/reviews, but does not
rewrite, the following accepted candidate inventory:

| Layer | Schema/record inventory | Journal/count boundary |
|---|---|---|
| M1a/M1b | schema v1 -> v2; 13 M1a domain tables, 15 v2 domain tables, 17 v2 expected tables including metadata/journal | exactly two named schema migrations: `m1a-inert-schema-v1`, `m1b-legacy-backfill-ledger-v2` |
| M2b-b/c | isolated schema v3; `m2b-immutable-ledger-v3`; append-only/anchored domain repository | no owner migration performed by this package |
| MissionContext | isolated schema v4; migration `M4-P4.3-MISSION-CONTEXT-V1`; 17 physical tables/16 content tables in current source | no production journal row or owner context created here |
| P4.4/R10 | isolated schema v5, record schema v3, 14 immutable table names; typed evidence, claim, artifact, action request/receipt and event contracts | direct isolated initialization only; not a production-sidecar migration |

ADR delta: none; ADR-0001/0002 remain controlling.  API/event delta: none.
Stable core contracts and defaults are unchanged.

### Threat, data, license and operational impact

- Threat delta: no new authority, identity source, connector, dispatch or
  startup surface.  Unknown schema/workspace/outcome remains fail-closed.
- Data delta: no owner database/config/credential/memory/mission write and no
  provider payload.  Test artifacts live only in isolated basetemps/evidence.
- License delta: no dependency or distributable added; proprietary release
  remains `BLOCKED_BY_LICENSE`.
- Resource/cost: local CPU/RAM/disk only for verifier/tests; no token, API,
  provider or financial cost.  Measured durations and artifact bytes are in E3.
- Limitations: default-off fixture evidence cannot prove canonical Windows
  activation, live owner wiring, credential/browser isolation, provider/device
  behavior or cross-platform packaging.

### Reviewer runbook

1. Reconstruct `VE-SCOPE-P4-E1E5-001.sha256` and R10 using the verifier.
2. Confirm the JSON/JUnit hashes and zero failures/errors/unexplained skips.
3. Confirm all eight process flags were false and no Onyx restart occurred.
4. Compare the matrix delta: no capability status may be promoted.
5. Review retained blockers and select an E6 decision explicitly.

Recommended decision while E1 blockers remain: **do not activate; retain the
accepted R10 slice default-off and schedule blocker closure**.  This file does
not itself make or accept E6 and does not unlock Phase 5.
