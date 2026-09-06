# Onyx implementation roadmap

Status: **historical Phase 0 roadmap; superseded for current execution by
`CURRENT_RELEASE_STATUS.md` and
`DOCUMENT_SUPERSESSION_REGISTRY_R15B_2026-08-11.md`.** Retained to preserve the original phased design
and evidence lineage. It does not claim that V37 is built, installed or release
eligible. Current source authority is the **current authenticated source
evidence selected by the [direct verifier](../../scripts/verify_phase5_exit_retirement_v1.py)**,
which authenticates the current Phase and Release Workflow transitions and
their complete immutable predecessor chains.

Status: Phase 0 execution roadmap, 2026-07-14. This roadmap implements Phases 4-16 of `plans/onyx-advanced-entity-redesign.md` using the gaps in `GAP_ANALYSIS.md`. It preserves the implemented Phase 1 identity contract, Phase 2 Orb bridge and Phase 3 mission worker/verifier as protected foundations.

## 1. Delivery rules

1. **One core:** no second mission engine, permission boundary, dispatcher, memory compatibility API or permanent UI shell.
2. **Additive first:** new records live in `runtime/control_plane.sqlite3` and workspace artifact roots before any existing schema change is considered.
3. **Flags default off:** every Phase 4+ runtime slice has an explicit feature flag, legacy-compatible default and tested rollback. In this roadmap, **activation** means enabling an extension flag for live/default runtime use at its phase exit; it does not mean beginning implementation or exercising the extension explicitly in isolated tests.
4. **Evidence before status:** code, schema or UI presence does not make a capability working. Status changes require proportional tests and observed behavior.
5. **One provider/test account at a time:** for each external domain, prove health/read -> draft/dry-run -> one reversible mutation -> observation/reconciliation before adding another provider or enabling broader actions.
6. **No silent fallback:** a blocked official API remains blocked. Browser/UI fallback is separately labeled, scoped and audited.
7. **No blind retry:** a timeout after dispatch is `unknown`; reconcile provider state before retry.
8. **Authority remains human:** credentials, account enrollment, publication, sending, spend, purchase, deploy/merge/delete, license and policy expansion require the approval class defined in `APPROVAL_POLICY.md`.
9. **Stop after every gate:** update `CAPABILITY_MATRIX.md`, threat/license findings and rollback evidence before beginning the next slice.
10. **No implicit legacy fallback:** only an explicit `LegacyWorkspaceAdapter` call may select `legacy-default`. A new or enhanced request with a missing/unknown workspace fails closed; omission never expands to global legacy data.

## 2. Protected baseline: Phases 1-3

| Phase | Preserved capability | Regression boundary |
|---|---|---|
| 1 | Cyryx Onyx identity, truthful prompt, owner-name migration and legacy compatibility | `core/identity.py`, `core/prompt.txt`, identity/migration regressions; no reintroduction of third-party fictional branding |
| 2 | One GPU Orb bridge with real QML loading, reduced-motion/minimize lifecycle and software fallback | `qml/OnyxOrb.qml`, `core/orb_state.py`, `ui.py:OrbHost`, Orb/performance tests; no extra render loops/widgets |
| 3 | One persistent mission engine/worker with structured evidence/postconditions, leases, pause/cancel, late-result rejection and explicit resolution | `core/missions.py`, `core/mission_tools.py`, mission tests; no second queue/state machine or direct sidecar writes into mission tables |

Any failure in this boundary blocks Phase 4+ activation. Defect fixes must retain public behavior and add regression evidence.

The controlling architectural decisions are:

- `adrs/ADR-0001-stable-core-extension.md` — stable-core compatibility boundary;
- `adrs/ADR-0002-workspace-and-evidence-sidecars.md` — workspace/control-plane sidecars;
- `adrs/ADR-0003-capability-nexus-and-mcp.md` — connector and MCP normalization;
- `adrs/ADR-0004-model-router-and-provider-adapters.md` — model routing and Operator Cells;
- `adrs/ADR-0005-qt-quick-shell-migration.md` — callback-safe, resource-bounded shell migration.

## 3. Release and slice order

| Release | Phases | Ordered slices | Primary dependency | Release checkpoint |
|---|---:|---|---|---|
| R0 Phase 0 closure | 0 | Accept audit -> matrix -> gaps -> architecture/security/data/approval/license docs -> ADR-0001 through ADR-0005 -> roadmap | Current-tree evidence | Ten Phase 0 output categories and the full ADR set reviewed; unresolved items remain truthfully blocked |
| R1 Trust foundation | 4-6 | Contract freeze -> inert sidecar -> `legacy-default` -> mission context -> typed evidence/actions -> grant shadow mode -> legacy capability descriptors -> one local MCP/read adapter -> separate Gemini Live and local/text compatibility wrappers -> Cell pair | R0 | Extension-off equivalence, zero widening, modality-specific rollback and one read-only vertical slice proven |
| R2 Company Command | 7-8 | Workspace memory/credential/profile/artifact adapters -> Company Graph -> Founder Brief -> one executive provider read -> draft -> reversible mutation | R1 | Zero cross-workspace leakage; sourced daily brief; test-account action receipt/reconciliation |
| R3 Intelligence | 9 | Approved source registry -> dated claims -> contradictions/freshness -> opportunity queue -> monitored digest | R2 evidence/graph | Groundedness/date/injection evaluations pass; Argos (proprietary) world-intelligence built in-house or omitted |
| R4 Social Organic | 10 | Brand passport -> local content plan/draft -> one provider health/read -> draft -> approved test publication -> analytics observation | R1 plus test account | Exact account binding, idempotent receipt and observed publication/analytics on test account |
| R5 Browser and Project Autopilot | 11 | Workspace profile/worktree -> allowlists/redaction -> signed envelope -> reversible local mission -> takeover/kill/recovery -> optional external-agent adapter | R1 | Drift, restart, unrelated-change and kill-switch E2E pass; no deploy/merge/spend/delete authority |
| R6 Paid Growth | 12 | One provider reporting -> measurement audit -> draft change set -> create-paused -> bounded test mutation -> reconciliation | R1 plus owner economics/access | Hard spend rules and exact approval proven; no real spend automated fixture |
| R7 Travel | 13 | Authorized inventory read -> compare/shortlist -> reprice -> exact booking request -> separately approved booking/reconciliation | R1 plus provider/market design | Search coverage disclosed; uncertain payment never retried; receipt/reference verified |
| R8 Knowledge Refinery | 14 | Approved local discovery -> candidate writes -> source scoring/corroboration -> bounded scheduler -> morning digest -> reviewed promotion | R1/R2 memory boundaries | Candidate-only pipeline passes poisoning, rights, budget, restart and kill-switch tests |
| R9 Command Center | 15 | Read-only projections -> approval inbox -> domain surfaces -> voice/state sync -> authenticated remote parity -> observability -> optional unified QML shell | Stable R1-R8 schemas | Callback parity, truthful state labels, accessibility, remote auth and CPU/GPU budgets pass |
| R10 Hardening/release | 16 | Adversarial/chaos/load -> locks/SBOM/notices -> license decision -> signing/notarization -> clean-machine matrix -> runbooks -> publication gate | All intended releases | Every capability status evidenced; no license/platform/security blocker for chosen distribution |

External-domain releases after R1 may be developed in separate branches, but no branch may duplicate control-plane contracts or activate a mutation before the shared R1 gates pass.

### Mechanical exit gate E1-E6

Every Phase 4-16 exit is mechanical. A phase cannot hand off to the next phase until all six records exist and the checkpoint is accepted:

1. **E1 — scope/blockers:** entry conditions and phase blockers are either closed with evidence or retained as a blocked capability outside the enabled slice.
2. **E2 — capability delta:** `CAPABILITY_MATRIX.md` records each affected capability's before/after status, exact evidence ID, limitations, owner and next action. A status stays unchanged when proof is incomplete.
3. **E3 — verification bundle:** a durable manifest records tree/commit hash, commands, interpreter/dependency set, platform, timestamp, pass/fail/error/skip counts and linked logs/artifact hashes. Test names alone are not evidence. Relevant dependency-complete suites have no collection errors or unexplained skips.
4. **E4 — safety/rollback:** denial, failure, cancellation, restart, unknown-outcome and phase-specific security tests pass; the documented feature-flag rollback is exercised without destructive core migration.
5. **E5 — checkpoint package:** ADR/schema/API/event deltas, migration journal/counts, threat/data/license changes, resource/cost impact, limitations and runbook/reconcile/revoke steps are captured.
6. **E6 — acceptance:** the named checkpoint is reviewed and accepted. Until acceptance, the feature remains off by default and the next phase or mutation tier is blocked.

## 4. Phase execution contracts

### Phase 4 — Trust foundation and additive domain contracts

**Gaps:** G01-G04.

**Entry gate**

- Phase 0 artifacts and ADR-0001 through ADR-0005 accepted.
- Dependency-complete baseline environment identified; missing-dependency collection results are not treated as product regressions.
- Phase 1-3 focused suites and representative database fixtures are available.

**Ordered slices**

1. P4.0 freeze `MissionStore`, permission, dispatcher, memory, credential, dashboard, Orb, paths and package contracts with sanitized schema v1/v2/v3 fixtures and declaration/policy snapshots.
2. P4.1/M1a add `control_plane_v1` default-off flag, schema metadata/migration journal and an otherwise inert `runtime/control_plane.sqlite3` service. M1a creates no workspace, mission-context, memory-reference or domain rows and ends at the first review checkpoint.
3. P4.2/M1b begins only after M1a acceptance: create `WorkspaceRegistry`, add an explicit `LegacyWorkspaceAdapter` that alone may select `legacy-default`, then perform reviewed sidecar-reference backfills with source hash/count and idempotency journal. New/enhanced calls with missing or unknown workspace deny instead of falling back.
4. P4.3 add `MissionContextStore`, validated operational phases and typed events keyed to existing mission IDs; existing states remain authoritative.
5. P4.4 add versioned `EvidenceRecord`, `Claim`, `ActionRequest`, `ActionReceipt`, `EventEnvelope` and content-addressed artifact service around one provider-free mission tool.

**Tests and DoD evidence**

- Extension flags off produce identical public results and no new required data.
- Mission fixtures v1/v2/v3 and memory v1 remain readable and legacy records unchanged.
- Sidecar missing, corrupt, unknown-version or partially backfilled fails closed for enhanced work and never changes mission state or permission. Only an explicit legacy-adapter call may resolve `legacy-default`.
- Two synthetic workspaces show zero unauthorized retrieval across mission context, memory metadata, artifact references and roots.
- Every sampled mutation-shaped action has stable idempotency key, request, audit reference, receipt and observed postcondition; secrets never enter rows/artifacts/logs.
- Migration/restart/backfill/rollback tests and current Phase 1-3 regression suites pass.
- `CAPABILITY_MATRIX.md`, schema docs, threat model and ADR delta are updated with exact evidence.

**Checkpoint/rollback**

- Checkpoint after each P4 slice; no combined schema-and-behavior cutover.
- Disable `control_plane_v1`; the existing runtime ignores the sidecar. Preserve it for diagnosis/export; delete only after verified export and explicit authorization.

**Exit gate**

- E1-E6 are complete for G01-G04; current defaults are unchanged; the capability-matrix delta links the verification bundle; M1a and M1b checkpoint evidence is distinct; and the sidecar cannot broaden authority. `control_plane_v1` activation means enabling it for the accepted live slice only after this Phase 4 exit.

### Phase 5 — Grants, approval inbox and Capability Nexus

**Gaps:** G05-G06.

- **Entry:** Phase 4 exit; trusted session identity and typed action digest available.
- **Slices:** grant schema/revoke/kill -> shadow evaluator -> approval inbox read projection -> exact low-risk enablement -> legacy capability descriptors -> one local read-only connector contract.
- **DoD/tests:** payload/target/workspace/session/cost/expiry/use drift denies; always-explicit actions cannot be granted; audit failure and kill switch revoke/stop; connector health/scope/rate-limit/cancel/unknown/reconcile/degraded-mode contract passes.
- **Rollback:** `grant_evaluator=false` routes all consequential requests to current callback; disable connector descriptors without changing legacy dispatch.
- **Blockers:** no routine grant activation before shadow replay proves zero over-grant.
- **Exit gate:** E1-E6 complete with matrix deltas for grants, approval inbox and Capability Nexus; the accepted checkpoint links exact-match/revoke/kill, connector-contract and rollback evidence before Phase 6 begins.

### Phase 6 — Model router, MCP and external-agent adapters

**Gap:** G07 plus the adapter part of G06.

- **Entry:** Phase 5 connector and grant contracts stable.
- **Slices:** characterize and separately wrap Gemini Live (`main.py:OnyxLive` + `core/live_model.py`) and local/text (`core/llm_client.py` Ollama/OpenAI-compatible) with unchanged call sites/defaults -> registry/health -> privacy-hard router -> provider-free research Cell + independent verifier -> one local read-only MCP adapter -> disabled external-agent descriptor.
- **DoD/tests:** extension-off equivalence and golden evaluations are separate for Live audio/streaming and standalone text; passing one modality never activates the other; privacy constraints cannot be outscored; unavailable/cancel/fallback/budget behavior and adapter auth/cancel/receipt semantics pass without silent cross-routing.
- **Rollback:** disable router/Cells/MCP per modality; Gemini Live returns to `OnyxLive`/`resolve_live_model`, local/text returns to `core/llm_client.py`, and the existing dispatcher/mission tools remain active. No rollback merges, proxies or silently redirects one path through the other.
- **Blockers:** external agent remains `BLOCKED_BY_ACCESS` until installed/authenticated permitted test environment exists.
- **Exit gate:** E1-E6 complete with separate matrix/evidence deltas for Gemini Live compatibility, local/text compatibility, router, Cells and MCP; the accepted checkpoint links modality-specific parity, privacy, fallback, golden-evaluation and rollback evidence before Phase 7 or any cross-route/additional provider begins.

### Phase 7 — Company Graph and layered memory

**Gaps:** G08-G09.

- **Entry:** workspace isolation and typed evidence proven.
- **Slices:** workspace memory filters -> credential/profile/artifact aliases -> approved-source registry -> read-only graph -> contradiction/freshness -> Founder Brief/portfolio projection.
- **DoD/tests:** pre-ranking isolation; zero cross-workspace export/delete/retrieval; no secret alias resolution outside workspace; source-grounded graph and stale/conflict/golden brief evaluations.
- **Rollback:** disable adapters/projection; retain legacy memory and source artifacts; never copy secrets back to JSON.
- **Blockers:** no company fact becomes authoritative solely through similarity or model assertion.
- **Exit gate:** E1-E6 complete with matrix deltas for workspace memory, aliases, Company Graph and Founder Brief; the accepted checkpoint proves zero leakage and sourced projection behavior before Phase 8 begins.

### Phase 8 — Executive office and daily operations

**Gap:** G10.

- **Entry:** Phase 5 connector contracts, Phase 7 workspace identity, owner-selected provider/test account and OAuth scopes.
- **Slices:** health/scopes -> read-only email/calendar/tasks/docs -> local draft -> provider draft where supported -> one reversible approved mutation -> observe/reconcile.
- **DoD/tests:** wrong account/recipient/time zone/target, pagination, revoke, rate limit, duplicate, timeout-after-dispatch and provider-state observation; every mutation has exact approval/valid grant and receipt.
- **Rollback:** disable descriptor/revoke alias; unresolved effects wait for reconciliation; local reminder/UI fallbacks remain separately labeled.
- **Blockers:** `BLOCKED_BY_ACCESS` until test account and current provider terms are documented.
- **Exit gate:** E1-E6 complete for the single selected provider with read/draft/mutation matrix deltas kept separate; the accepted test-account checkpoint links account/scope/idempotency/receipt/reconciliation evidence before another provider or Phase 9 handoff.

### Phase 9 — Intelligence and opportunity radar

**Gap:** G11.

- **Entry:** typed evidence/claims, workspace/company sources and monitoring budget.
- **Slices:** source registry -> read-only collection -> dated claims/inferences/unknowns -> contradiction/freshness -> opportunity scoring -> scheduled cited digest.
- **DoD/tests:** groundedness, primary-source/date, freshness expiry, contradiction, prompt injection, dedupe, monitoring restart and alert-quality evaluations.
- **Rollback:** stop monitor/projection; preserve evidence and on-demand search.
- **Blockers:** none from licensing — the dropped third-party World Monitor is replaced by the 100%-proprietary Argos (not yet built), which copies no external source/UI/assets.
- **Exit gate:** E1-E6 complete with intelligence/monitoring matrix deltas and a groundedness/freshness/injection evidence bundle; the accepted checkpoint scopes out Argos as a proprietary, not-yet-built successor to the dropped World Monitor.

### Phase 10 — Social organic operating system

**Gap:** G12.

- **Entry:** one officially approved test account, brand passport/content rights and Phase 5 connector contract.
- **Slices:** account health/read -> content/calendar local draft -> provider draft -> exact approved test publish -> observed post/ID -> analytics read -> community inbox read.
- **DoD/tests:** exact account/workspace, media validation, duplicate/idempotency, scope/revoke, rate limit, timeout/reconcile, edit/delete policy and analytics source; UI fallback never masquerades as API success.
- **Rollback:** disable/revoke connector; keep local drafts; reconcile unknown publication before retry.
- **Blockers:** every additional platform waits until the first platform vertical slice passes and the matrix is reviewed.
- **Exit gate:** E1-E6 complete for one test platform with distinct read/draft/publish/analytics matrix deltas and observed provider-state evidence; the checkpoint is accepted before another platform or Phase 11 handoff.

### Phase 11 — Browser/computer control and Project Autopilot

**Gap:** G13.

- **Current checkpoint (2026-07-30):** isolated local software mission and
  independent state verifier have an executable default-off V1 candidate under
  signed bounds. Restart never auto-resumes an old checkpoint; an explicit
  exact-state fresh-reapproval flow now reseeds a new pending mission. Patch
  plaintext is never materialized to disk: bounded decrypted bytes flow only
  through trusted Git stdin, while checkpoint/status/verifier access shares the
  per-mission cross-process lock and live disk monitoring has
  file/directory/depth/time bounds. A separate default-off Windows
  handle-relative cleanup candidate now binds prepare/finalize provenance,
  terminal MissionStore state and resumable deletion receipts; the default
  path still refuses cleanup. Stages A-E additionally pin Live binding/artifact
  I/O to trusted parent/root handles, stream the protected Git bundle into
  reserved storage, apply typed add/modify patches handle-relative, cap
  refcounted mission locks and non-evicting high-water caches, and complete
  Windows Job HANDLE signatures. The reproduced proportional gate is 2,181
  passed, 6 skipped and 92 subtests. Metadata inherits the trusted parent ACL;
  no same-user/admin confidentiality, hardware-power-loss durability or
  non-Windows cleanup claim is made. Phase 11 remains `PARTIAL`: executable process
  sandbox, browser/computer envelopes, takeover and E6 remain. A Claude Code
  patch-output External Agent Adapter V1 is now source-wired through
  MissionStore/Phase 11/V15 with clone-only, no-tool/no-MCP execution and no
  publish authority; independent E6, one approved low-cost provider mission
  and rebuilt installed-host proof remain.

- **Attempt reconciliation checkpoint (updated 2026-08-01):** an authenticated,
  append-only MissionStore decision record now supports `still_unknown`
  (continues to block) and `abandon` (anchor first, then kill/cancel), with
  idempotent restart handling and redacted live status. Neither path retries or
  dispatches. The original attempted intent remains unchanged. The current
  executable boundary now live-wires a local host-owned dispatch/receipt ledger.
  `recovered_receipt` accepts only its exact authenticated canonical receipt for
  the original mission/execution/attempt; invalid or missing evidence stays
  unknown with no redispatch. `proven_not_executed` remains fail closed and no
  missing container/process is treated as proof. There is still no retry,
  external monotonic anchor, real-Docker proof, installed-package proof or E6.

- **Governed browser Away V1 checkpoint (2026-07-30):** Windows V15 now
  live-wires one anonymous, public-HTTPS, read-only Playwright observation
  through MissionStore and the Phase 11 authority boundary. Its immutable
  envelope binds principal, Away session, lease generation, workspace/profile,
  provider/account class, exact URL/origin/domain allowlist, action, approval
  window, one-use/network/output/screenshot/paid-cost budgets, approval digest,
  key epoch and stop policy. A host-signed runtime deadline starts at the
  approved lease/dispatch boundary and binds the immutable plan, execution
  identity and DNS pin; `max_seconds` is capped at the 60-second production
  worker lease. Actual Chromium launch/close availability is cached only for
  short informational checks and repeated authoritatively before durable intent.
  A create-once
  authenticated intent is flushed before navigation; any post-intent uncertainty is
  `attempted_unknown`, and neither `still_unknown` nor terminal `abandon`
  redispatches. Headed preview, terminal pause/takeover records, durable
  per-mission/global kill with explicit incomplete reporting, late-result
  quarantine, exact target verification, Chromium resolver pinning plus
  all-global route checks, context-wide HTTP routing, WebSocket denial and
  QUIC/WebRTC/WebTransport suppression, descriptor-bound storage, profile
  identity protection with handle-relative Windows quarantine, opaque artifact
  references, DOM masking, receipt persistence and ordered
  worker/authority/handle shutdown are implemented. Transient binding or Away
  root contention now degrades the affected capability unavailable instead of
  crashing startup, while invalid ACL/namespace state remains a distinct
  fail-closed reason. Focused hardening gates passed 90 tests with the opt-in
  smoke skipped by default; Phase 11 live plus activation/onboarding regression
  passed 63 tests plus 11 subtests with one platform skip; and one opt-in real
  headed `example.com` smoke passed. This is not Phase 11 exit:
  authenticated browser
  accounts, clicks/forms/uploads/downloads, provider mutations, verified native
  window/DPI computer control, installed-package proof and independent E6
  remain open.

- **Entry:** workspace profiles, grants/envelopes, kill switch, evidence/actions and isolated-worktree policy.
- **Slices:** profile/root/domain allowlists -> screenshot/clipboard redaction -> checkpoint/takeover -> signed reversible browser task -> isolated local software mission -> independent verifier -> optional external-agent test adapter.
- **DoD/tests:** wrong target/domain, UI drift/dialog/DPI, MFA/CAPTCHA/lockout, unrelated working-tree changes, restart, budget, pause/takeover/resume/kill and rollback; no unauthorized deploy/merge/delete/credential/spend.
- **Rollback:** stop envelope, cancel worker, retain checkpoint/worktree and set mission waiting/reconciliation.
- **Blockers:** no Away Mode under a broad or unsigned grant.
- **Exit gate:** E1-E6 complete with separate browser, computer-control, Project Autopilot and external-agent matrix deltas; the accepted checkpoint links drift/redaction/takeover/kill/recovery evidence before broader Away Mode or Phase 12 handoff.

### Phase 12 — Paid Growth command

**Gap:** G14.

- **Entry:** one official sandbox/test account, verified conversion/consent/attribution inputs, hard spend policy and owner-approved economic bounds.
- **Slices:** read reporting -> measurement audit -> local draft -> provider draft/create-paused -> exact approved bounded test mutation -> observe/reconcile -> bounded optimization only after evaluation.
- **DoD/tests:** attribution limits stated, scope/revoke/rate limit, hard daily/total budgets, create-paused, before/after receipts and reconciliation. Real spend is never an automated fixture.
- **Rollback:** disable/revoke; pause staged entities where exactly authorized; never raise/remove spend caps automatically.
- **Blockers:** billing, enablement, material targeting/geography/conversion and spend increases remain always-explicit or within an exact approved bound.
- **Exit gate:** E1-E6 complete for one test ads provider with reporting, measurement, draft/create-paused and any mutation status separated in the matrix; the accepted checkpoint links hard-budget and reconciliation evidence before optimization or Phase 13 handoff.

### Phase 13 — Travel intelligence

**Gap:** G15.

- **Entry:** authorized inventory test environment, market/consolidator decision and approved traveler/payment boundary.
- **Slices:** inventory health/read -> compare/coverage disclosure -> shortlist -> reprice/availability -> exact booking request -> separately approved booking -> booking reference/receipt observation.
- **DoD/tests:** passenger/airport/date/time-zone/cabin/baggage/terms/total/currency validation, fare expiry, duplicate, uncertain payment reconciliation and final confirmation.
- **Rollback:** disable provider and preserve shortlist/receipts; unresolved payment remains waiting.
- **Blockers:** no claim of exhaustive inventory; no retry of uncertain payment.
- **Exit gate:** E1-E6 complete with search, reprice and booking capabilities represented separately in the matrix; the accepted checkpoint links coverage, exact-confirmation and payment-reconciliation evidence before Phase 14 handoff.

### Phase 14 — Nighttime Knowledge Refinery

**Gap:** G16.

- **Entry:** workspace/evidence/memory boundaries, authorized-source policy, resource budgets and kill switch.
- **Slices:** approved local corpus -> dedupe/source score -> candidate-only memory -> corroboration/conflicts/expiry -> bounded scheduler -> morning digest -> reviewed promotion workflow.
- **DoD/tests:** restart, dedupe, injection/poisoning, rights/access, candidate isolation, promotion denial, expiration, CPU/GPU/token/storage/network cost and kill switch.
- **Rollback:** stop schedule and export/delete candidates under retention policy; existing memory remains unchanged.
- **Blockers:** never bypass access controls or autonomously deploy, broaden permission, add credentials, change runtime policy/code/tools or retrain production models.
- **Exit gate:** E1-E6 complete with discovery, candidate, promotion and scheduler matrix deltas separated; the accepted checkpoint links poisoning/rights/budget/restart/kill evidence before Phase 15 handoff.

### Phase 15 — Command Center, spatial shell and observability

**Gap:** G17.

- **Entry:** stable data/projection contracts for every included domain and callback parity inventory.
- **Slices:** read-only mission/evidence/capability/cost projections -> approval inbox -> Founder/intelligence/domain views -> authenticated remote parity -> voice/state sync -> accessibility/adaptive quality -> optional single Qt Quick shell cutover.
- **DoD/tests:** callback parity, truthful verified/partial/unverified/blocked/simulated labels, keyboard/reduced motion, visual regression, responsive/remote auth, idle CPU/GPU, active frame-time and adaptive-quality budgets.
- **Rollback:** disable projections/new shell; current `OnyxUI`, Orb bridge and dashboard callbacks continue.
- **Blockers:** no UI claim without matching runtime capability status; no permanent duplicate shells.
- **Exit gate:** E1-E6 complete with projection and Qt Quick shell statuses separated in the matrix; the accepted checkpoint links callback/accessibility/truth/resource/package evidence before shell activation or Phase 16 handoff.

### Phase 16 — Hardening and cross-platform release

**Gap:** G18.

- **Entry:** intended capability scope frozen and matrix evidence current.
- **Slices:** adversarial/chaos/load/long-mission suites -> dependency locks -> SBOM/licenses/notices -> source/Qt/PyQt/asset decision -> signed/notarized artifacts -> clean-machine platform matrix -> backup/export/delete/incident/rollback runbooks -> controlled publication.
- **DoD/tests:** Windows, macOS Intel/ARM and Linux x64/ARM install/upgrade/uninstall/package smoke; QML/plugins/browser/audio/vault; secret/workspace/idempotency/unknown-response attacks; exact-artifact license/vulnerability policy; hashes/signatures.
- **Rollback:** keep/revoke artifacts as internal; publication fails closed on any security/license/platform gate.
- **Blockers:** proprietary/public release stays `BLOCKED_BY_LICENSE` until `OPEN_SOURCE_AND_API_LICENSE_REVIEW.md` gates have durable qualified evidence.
- **Exit gate:** E1-E6 complete for the chosen distribution scope; every shipped capability and host has a matrix/evidence delta, exact-artifact license/security/platform proof and accepted release checkpoint. Any unresolved blocker keeps publication disabled.

## 5. Universal Definition of Done per slice

Every slice must leave these artifacts:

1. Scope, exclusions, definition of done and capability-matrix delta.
2. Schema/API/event version and compatibility impact.
3. Threat/data/license update proportionate to the change.
4. Code plus unit, contract, integration/evaluation/E2E evidence appropriate to the claimed scope.
5. Success, denial, unavailable dependency, cancellation, timeout, restart and rollback evidence.
6. Exact migration/backfill journal and integrity counts when persistence changes.
7. Observability evidence without secrets or uncontrolled sensitive payloads.
8. Cost/quota/resource impact and enforced bounds.
9. User-facing state/limitations that match runtime truth.
10. Runbook, kill/revoke/reconcile path and clean rollback checkpoint.

A slice is not done if the full relevant test collection cannot run and the missing evidence is merely described. It may remain a reviewable checkpoint with truthful `PARTIAL`/blocked status, but it cannot unlock the next mutation gate.

## 6. Exact handoff into Phase 4

The first implementation handoff is deliberately narrow:

```text
Branch/checkpoint: phase4-m1a-inert-control-plane
Flags: control_plane_v1 = false by default
Runtime behavior change at first checkpoint: none
Persistence change: create a new inert schema/migration journal only; no domain rows or backfill
Existing database writes: none
External calls/mutations: none
```

Execute in this exact order:

1. Record current dependency-complete test command(s), missing-environment conditions and sanitized legacy fixture hashes. Do not claim the known 113/10-error/8-skip collection is green.
2. Add characterization tests for stable contracts named in `TARGET_ARCHITECTURE.md` section 2.
3. Define versioned control-plane domain types and migration journal with no dispatcher integration.
4. Create the M1a sidecar service, schema metadata and migration journal behind `control_plane_v1`; opening/closing it must not touch mission, memory or audit databases and must not create workspace/domain rows.
5. Do not insert `legacy-default`, backfill mission/memory references or add mission contexts in M1a. Specify the explicit `LegacyWorkspaceAdapter` contract for later M1b; a new/enhanced request with missing/unknown workspace must deny.
6. Add failure tests for absent/corrupt/unknown-version/read-only sidecar and missing/unknown workspace, proving enhanced behavior denies while an explicit legacy-adapter fixture and extension-off legacy behavior remain unchanged.
7. Run Phase 1-3 and new Phase 4 contract suites; capture exact pass/skip/error evidence and `git diff --check`.
8. Update `CAPABILITY_MATRIX.md`, ADRs and threat/data documents with actual results.
9. Stop for M1a review. Do not begin M1b, create `legacy-default`, backfill references/mission contexts or activate the flag for live/default use until this checkpoint is accepted.

**Phase 4 M1a first-checkpoint acceptance evidence:** no existing file/database migrated; no workspace/domain/backfill rows created; no runtime default changed; sidecar schema/migration journal is deterministic; unknown/corrupt state and missing/unknown enhanced workspace fail closed; explicit legacy-adapter behavior is specified separately; rollback is demonstrated by disabling/removing only the inert sidecar in a test data root; and all protected baseline evidence available in the dependency-complete environment remains green. Accepted M1a authorizes planning/implementation of M1b, not automatic flag activation.
