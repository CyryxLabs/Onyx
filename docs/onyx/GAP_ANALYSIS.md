# Onyx gap analysis

Status: **historical Phase 0 gap baseline; superseded for current release
status by `CURRENT_RELEASE_STATUS.md`.** The analysis remains useful as design
history, but later implementation may have closed or changed individual rows.

Status: Phase 0 implementation gap baseline, 2026-07-14. This analysis derives from `CAPABILITY_MATRIX.md`, `TARGET_ARCHITECTURE.md`, `THREAT_MODEL.md`, `APPROVAL_POLICY.md`, `DATA_AND_MEMORY_BOUNDARIES.md`, `OPEN_SOURCE_AND_API_LICENSE_REVIEW.md` and Phases 4-16 of `plans/onyx-advanced-entity-redesign.md`.

In this analysis, **activation** means enabling a Phase 4 feature flag for runtime use and satisfying the Phase 4 exit gate. Beginning implementation, creating an inert schema or running flags-off/shadow tests is not activation.

The current runtime is the compatibility boundary. A gap is closed only by runtime evidence and proportional verification; a target document, schema proposal, UI label or connector stub does not close it.

## Priority model

- **P0 — trust prerequisite:** omission can widen authority, leak workspaces/secrets, duplicate consequential actions or corrupt the working core.
- **P1 — operational prerequisite:** required for a dependable day-to-day assistant but must be built on P0 contracts.
- **P2 — experience/scale:** valuable after execution truth, isolation and rollback are stable.
- **P3 — release:** distribution evidence and legal obligations; cannot be inferred from local development success.

## Gaps

### G01 — Stable-contract freeze and reproducible baseline

- **Current status/evidence:** `PARTIAL`. The compatibility boundary is enumerated in `TARGET_ARCHITECTURE.md`. The project `.venv` passed 276 tests (`VE-UNIT-001`), pip consistency (`VE-PIP-001`), Ruff F/E9 (`VE-RUFF-001`) and compileall (`VE-COMPILE-001`). The baseline remains partial because browser tests were blocked by sandbox `spawn EPERM` (`VE-BROWSER-001`), readiness is not operationally verified (`VE-READINESS-001`), dependencies are not locked and the dirty worktree is not a release artifact. The earlier 113-test global-Python run is non-authoritative environment diagnostics.
- **Target contract:** M0 characterization fixtures for mission schemas v1/v2/v3, memory schema v1, tool declarations/policies, dashboard auth, paths and packaging; old callers behave identically with extension flags off.
- **Dependency:** reproducible development/test dependency set and representative sanitized fixtures.
- **Risk/priority:** P0. Building sidecars on an ambiguous baseline can conceal a regression or silently redefine the stable core.
- **Minimum additive change:** add fixture hashes and contract tests only; do not migrate runtime data.
- **Verification:** dependency-complete collection/execution, fixture round trips, declaration/policy snapshots, `git diff --check` and extension-off equivalence.
- **Rollback:** remove characterization-only additions; no persisted data changes.
- **Owning phase:** Phase 4 entry gate, with Phase 16 retaining the full baseline.

### G02 — Workspace registry and isolation

- **Current status/evidence:** `NOT_IMPLEMENTED`. `CAPABILITY_MATRIX.md` records one effectively global mission, memory, credential and browser context. `DATA_AND_MEMORY_BOUNDARIES.md` defines the required classes and filters.
- **Target contract:** `WorkspaceRegistry` keyed by `workspace_id`, with roots, artifact path, credential/browser/memory aliases, retention, data-class ceiling, connector/domain allowlists and lifecycle state; no credential value in the registry.
- **Dependency:** `runtime/control_plane.sqlite3`, migration journal and feature flag.
- **Risk/priority:** P0. Cross-client, employer, Cyryx and personal leakage would violate the plan's central boundary.
- **Minimum additive change:** M1a creates only the inert sidecar schema, empty tables/indexes and migration journal, with no workspace/domain row or `legacy-default`, then stops for mandatory review. After acceptance, M1b creates `WorkspaceRegistry` and `legacy-default` through the explicit versioned `LegacyWorkspaceAdapter`, then performs reviewed, idempotent mission/memory context backfill. Enhanced/new calls fail closed for absent, unknown, inactive or malformed workspace identity; only that adapter with a trusted host-owned legacy-caller marker may select `legacy-default`. Do not modify existing mission/memory schemas.
- **Verification:** two synthetic workspaces produce zero unauthorized mission, memory, artifact, credential and profile results; missing/corrupt rows never widen scope.
- **Rollback:** disable `control_plane_v1`; existing callers resolve to unchanged legacy behavior only where enhanced semantics are not required.
- **Owning phase:** Phase 4.

### G03 — Mission context and operational lifecycle sidecar

- **Current status/evidence:** `NOT_IMPLEMENTED`. `core/missions.py:MissionStore` provides the proven durable eight-state engine; no typed scope, exclusion, definition-of-done, autonomy, rollback or operational-phase record exists.
- **Target contract:** one-to-one `MissionContextStore` sidecar keyed by existing mission ID; operational phases map onto, never replace, current durable state.
- **Dependency:** G01-G02 and an idempotent mission-ID backfill.
- **Risk/priority:** P0. A second state machine or direct sidecar SQL into mission tables would fork execution truth.
- **Minimum additive change:** append context rows and typed phase events through an application service; keep `MissionStore` authoritative.
- **Verification:** v1/v2/v3 mission fixtures remain byte/logically stable; invalid phase transitions deny; sidecar loss cannot change mission state.
- **Rollback:** turn off context reads; preserve sidecar for diagnosis without reverse migration.
- **Owning phase:** Phase 4.

### G04 — Typed evidence, claims, action requests and receipts

- **Current status/evidence:** `NOT_IMPLEMENTED` at domain level. `normalize_mission_result`/`verify_mission_result` and hash-chained audits are `WORKING_AND_VERIFIED`, but they do not provide the proposed cross-source claim and external action ledger.
- **Target contract:** versioned `EvidenceRecord`, `Claim`, `ActionRequest`, `ActionReceipt` and `EventEnvelope`; content-addressed artifacts whose canonical relative path is exactly `<first-two-lowercase-sha256>/<lowercase-sha256>` after 64-lowercase-hex normalization/prefix validation; explicit `unknown` outcome; correlation across workspace/mission/audit/provider.
- **Dependency:** G02-G03, artifact retention policy and schema versioning.
- **Risk/priority:** P0. Without idempotency and observed-state receipts, timeouts can duplicate posts, messages, spend or purchases and unsupported claims can appear verified.
- **Minimum additive change:** sidecar-only records around one current provider-free mission tool, referencing rather than expanding the existing content-free audit.
- **Verification:** schema/property tests, secret redaction, hash/artifact validation, unknown-outcome reconciliation and proof that succeeded mutations require a satisfied postcondition.
- **Rollback:** disable typed ledger writes/read projections; current result/audit formats remain unchanged.
- **Owning phase:** Phase 4.

### G05 — Risk-scoped grants, approval inbox and global stop

- **Current status/evidence:** `NOT_IMPLEMENTED` for persisted grants/inbox; current exact callback/digest permission boundary is `WORKING_AND_VERIFIED`. `APPROVAL_POLICY.md` defines risk classes, exact matching and always-explicit actions.
- **Target contract:** signed/use-limited/expiring/revocable `AutonomyEnvelope` and `GrantEvaluator` matching principal, session, workspace, mission, tool, action, target, data class, cost and payload rules; calm batch approval; trusted kill state.
- **Dependency:** G02-G04, trusted session identity and UI projection.
- **Risk/priority:** P0. An approximate grant can silently become blanket access; an approval dialog for every harmless step defeats natural operation.
- **Minimum additive change:** shadow evaluator records `would_allow`/`would_deny` but never suppresses the current callback; then enable only low-risk exact matches.
- **Verification:** replay, payload/target/workspace/cost drift, expiry, use exhaustion, revocation, restart, emergency-stop and always-explicit denial tests.
- **Rollback:** one feature flag routes every consequential request back to the unchanged callback and revokes active grants.
- **Owning phase:** Phase 5.

### G06 — Capability Nexus and MCP contract

- **Current status/evidence:** `NOT_IMPLEMENTED`. `main.py:TOOL_DECLARATIONS` and direct `_execute_tool` dispatch are real; there is no normalized connector registry, MCP adapter or uniform health/scope/receipt contract.
- **Target contract:** versioned connector protocol for discovery, health/scopes/version, read/draft/mutate separation, credential alias, pagination, rate limits, dry run, idempotency, receipts, post-action observation, quota/cost and truthful degraded mode.
- **Dependency:** G02-G05 and credential aliases.
- **Risk/priority:** P0. Silent browser fallback or inconsistent connector semantics can bypass provider scopes and verification.
- **Minimum additive change:** register existing tools as legacy descriptors without changing dispatch; add one local read-only adapter before any external mutation.
- **Verification:** shared connector contract suite covering unavailable auth, scope loss, rate limit, cancel, timeout-after-dispatch, reconcile and disabled status.
- **Rollback:** disable descriptor/adapter; legacy dispatcher continues through the existing permission/audit boundary.
- **Owning phase:** Phase 5; MCP/external adapters continue in Phase 6.

### G07 — Model router and Operator Cells

- **Current status/evidence:** `PARTIAL`. The Gemini Live path is `main.py:OnyxLive` plus `core/live_model.py:resolve_live_model`; independently, `core/llm_client.py` exposes standalone Ollama and OpenAI-compatible local/text backends. No shared provider registry, privacy-hard routing, evaluated cross-provider fallback or versioned role profiles exist.
- **Target contract:** provider/model registry with privacy, modality, reliability, latency, evaluation, cost and availability policies; Operator Cells declare capabilities, data class, budget, evaluation and handoff while sharing the one mission engine.
- **Dependency:** G03-G06 and model/provider evaluation data.
- **Risk/priority:** P1. A second queue or router that treats privacy as a soft score would break architecture and data policy.
- **Minimum additive change:** preserve Gemini Live and local/text as two independent versioned compatibility adapters with their existing call sites, configurations and defaults; add one provider-free research Cell and independently instructed verifier Cell.
- **Verification:** prove extension-off equivalence separately for Gemini Live audio/streaming and `core/llm_client.py` text generation; use modality-specific golden evaluations plus privacy-denial, fallback, cancellation and budget tests. Passing one adapter cannot activate or establish parity for the other.
- **Rollback:** disable router/Cell profiles per modality; Gemini Live returns to `OnyxLive`/`resolve_live_model`, while standalone local/text callers return to `core/llm_client.py`. Rollback never cross-routes or merges the two paths.
- **Owning phase:** Phase 6.

### G08 — Workspace-aware memory, credentials, profiles and artifacts

- **Current status/evidence:** `NOT_IMPLEMENTED` as a boundary. `MemoryStore` and OS-vault credentials are individually `WORKING_AND_VERIFIED`, but global; browser profiles and artifacts lack the target workspace binding.
- **Target contract:** `WorkspaceMemoryAdapter` applies hard workspace/user/sensitivity/validity/freshness filters before ranking; opaque credential aliases, isolated browser profiles and content-addressed artifact roots follow the registry.
- **Dependency:** G02, G04 and storage/retention decisions.
- **Risk/priority:** P0. Relevance ranking or a legacy fallback must never cross a workspace boundary.
- **Minimum additive change:** dual-read sidecar metadata for new records; enhanced/new calls missing workspace fail closed. `legacy-default` is available only through the explicit versioned legacy adapter and trusted host-owned caller marker, never by generic fallback; no secret migration back to files.
- **Verification:** adversarial zero-leak search/export/delete/profile/credential tests; legacy memory remains readable with flags off.
- **Rollback:** disable workspace-aware adapters while retaining aliases/metadata; no destructive reverse copy.
- **Owning phase:** Phase 7 foundation.

### G09 — Company Graph and Founder Command

- **Current status/evidence:** `NOT_IMPLEMENTED`. Generic memory, search and proactive briefing exist, but no company entity/relationship/decision/portfolio graph or sourced Founder Brief projection exists.
- **Target contract:** authorized-source company graph with provenance, freshness, contradiction and decision status; read-only Founder Brief covering portfolio, blockers, decisions, opportunities, risks and top actions.
- **Dependency:** G04, G07-G08 and an owner-approved source registry.
- **Risk/priority:** P1. Unsourced or cross-workspace business guidance can create false operational authority.
- **Minimum additive change:** ingest approved local Cyryx evidence only into a read-only graph projection; facts, inferences and unknowns remain distinct.
- **Verification:** source-grounding/golden evals, stale/conflict behavior, workspace isolation and deterministic projection tests.
- **Rollback:** disable graph projection; preserve approved source artifacts and current memory behavior.
- **Owning phase:** Phase 7.

### G10 — Executive office connectors

- **Current status/evidence:** `PARTIAL`. Phase 8 accepted default-off Microsoft Graph read, OAuth, calendar, mail, tasks and OneDrive connector contracts, with a point-in-time live calendar/mail read recorded separately in the capability matrix. Operational Integration V14 now exposes only `day_brief_read` through the existing live host dispatcher: host authorization occurs before the deferred canonical factory validates the accepted workspace/credential alias and real native-vault token, restores OAuth or performs network I/O. Missing configuration, binding or token returns safely with zero HTTP calls. Focused DayOps/factory/V14 tests and the proportional V13 + Phase 6 Live Wiring + Graph Read/OAuth/Live Read selection pass, but no current V14 live-provider E2E or E6 acceptance is claimed.
- **Target contract:** one official provider vertical slice progressing read-only -> draft -> reversible approved mutation, with account/workspace binding, scopes, idempotency, receipt and observed final state.
- **Dependency:** G02-G06, OAuth application/scopes, test account and current provider terms.
- **Risk/priority:** P1/H. Wrong-recipient mail, calendar mutation or document disclosure requires exact identity and reconciliation.
- **Minimum additive change:** retain the V14 read-only daily-brief surface, run an explicitly authorized redacted live read with the existing Microsoft account, and reconcile the observed provider result before adding another operational route; do not silently fall back to browser automation.
- **Verification:** wrong account/recipient/time zone/scope, revoke, pagination, rate limit, duplicate, timeout-after-dispatch and post-state tests on a test account.
- **Rollback:** disable connector descriptor, revoke alias and leave unresolved effects in mission `waiting`.
- **Owning phase:** Phase 8.

### G11 — Intelligence and opportunity radar

- **Current status/evidence:** `PARTIAL`. `actions/web_search.py` and proactive briefing can retrieve information; there is no durable claim lifecycle, contradiction/freshness monitor or evaluated opportunity queue. World-intelligence is planned as the 100%-proprietary Argos (replacing the dropped third-party World Monitor); not yet built.
- **Target contract:** source registry, dated evidence/claims, freshness/validity, contradiction, confidence, opportunity scoring and cited monitoring; honest unknown/blocked states.
- **Dependency:** G04, G07-G09, source rights and monitoring budgets.
- **Risk/priority:** P1. Time-sensitive or licensed data can be stale, fabricated or unlawfully reused.
- **Minimum additive change:** produce a cited read-only digest from approved sources; world-intelligence via the proprietary Argos is a separate future build, omitted until an Argos slice is accepted.
- **Verification:** groundedness, primary-source preference, date/freshness, contradiction, injection, dedupe and alert-quality evaluations.
- **Rollback:** stop scheduler/projection; retain evidence and current on-demand search.
- **Owning phase:** Phase 9.

### G12 — Social organic operations

- **Current status/evidence:** the official social connector is `BLOCKED_BY_ACCESS`. Separately, `actions/send_message.py` is a `WORKING_WITH_LIMITATIONS` UI fallback with unit/policy evidence in `VE-UNIT-001`; browser execution was blocked in `VE-BROWSER-001` and it cannot prove provider delivery/analytics.
- **Target contract:** brand/content planning, draft/review, official publish, community inbox and analytics through one test-account connector with exact account/workspace binding and receipts.
- **Dependency:** G02-G06, provider app review/scopes/test account, brand passport and content rights.
- **Risk/priority:** P1/H. Wrong-account publication, duplicate content and unsupported performance claims are external reputation risks.
- **Minimum additive change:** official read-only account/content health and draft creation for one provider; keep fallback separately labeled.
- **Verification:** wrong account, media validation, rate limit, revoke, duplicate/idempotency, timeout/reconcile, delete/edit policy and analytics-source tests.
- **Rollback:** disable connector and revoke alias; drafts/artifacts remain local; never retry unknown publication blindly.
- **Owning phase:** Phase 10.

### G13 — Browser/computer control and Project Autopilot

- **Current status/evidence:** `PARTIAL`. Real browser, computer, file, code-helper and dev-agent actions exist, but target/domain allowlists, workspace profiles, redaction, signed Away Mode, takeover and independent verification are absent.
- **Target contract:** bounded browser/project missions under `AutonomyEnvelope`, isolated profile/worktree, checkpoints, drift/dialog/domain-change fail-closed behavior, pause/takeover/resume/emergency stop and independent verifier.
- **Dependency:** G02-G07 and platform-specific foreground/accessibility controls.
- **Risk/priority:** P0/H. UI drift or unrelated working-tree state can cause privileged, irreversible or secret-bearing actions.
- **Minimum additive change:** one reversible local project mission in an isolated workspace with no deploy/merge/spend/delete authority.
- **Verification:** drift, wrong target, CAPTCHA/MFA/lockout, clipboard/screenshot redaction, restart, budget, unrelated-change and kill-switch E2E.
- **Rollback:** stop envelope, cancel worker, preserve checkpoint/worktree and return mission to safe waiting/reconciliation.
- **Owning phase:** Phase 11.

### G14 — Paid Growth

- **Current status/evidence:** `BLOCKED_BY_ACCESS`; no Meta Marketing or Google Ads connector, measurement audit or runtime spend policy exists.
- **Target contract:** verified reporting/measurement first; then draft change set, create-paused, exact approval-gated launch and bounded optimization with hard daily/total spend and before/after receipts.
- **Dependency:** G02-G06, official developer access/test accounts, conversion/consent/attribution evidence and owner-approved economics.
- **Risk/priority:** P0/H. Money, targeting, geography and conversion changes cannot rely on model intent or UI claims.
- **Minimum additive change:** read-only reporting plus measurement integrity audit; no real spend fixture.
- **Verification:** scope/revoke/rate-limit, attribution uncertainty, hard-budget enforcement, create-paused and reconciliation tests in sandbox/test account.
- **Rollback:** disable connector/revoke alias; pause staged entities where authorized; preserve receipts and never remove spend caps automatically.
- **Owning phase:** Phase 12.

### G15 — Travel intelligence and booking

- **Current status/evidence:** search is `WORKING_WITH_LIMITATIONS` in `actions/flight_finder.py`; booking is `BLOCKED_BY_ACCESS`. Current parsing is non-exhaustive and has no licensed inventory, reprice, order or receipt.
- **Target contract:** authorized search/shortlist with coverage disclosure, then reprice/availability and exact passenger/airport/date/time-zone/cabin/baggage/terms/total/currency approval; booking reference observed after purchase.
- **Dependency:** G02-G06, provider credentials, market/consolidator decision and secure traveler/payment boundary.
- **Risk/priority:** P1/H/C. Wrong passenger/date/airport or uncertain payment cannot be retried blindly.
- **Minimum additive change:** read-only inventory comparison; keep identity/payment user-entered or in an approved encrypted vault.
- **Verification:** coverage, time zone, fare/fee/terms, reprice, expiry, duplicate, timeout/payment reconciliation and final-confirmation tests.
- **Rollback:** disable provider; preserve shortlist/receipts; unresolved payment remains waiting for reconciliation.
- **Owning phase:** Phase 13.

### G16 — Nighttime Knowledge Refinery

- **Current status/evidence:** `NOT_IMPLEMENTED`. There is no bounded overnight discovery, lawful acquisition, candidate-memory promotion, corroboration or morning-digest pipeline.
- **Target contract:** 23:00-06:00 bounded pipeline with source allow/deny/diversity, resource/cost limits, candidate-only writes, corroboration/primary-source gates, conflict preservation, expiry and reviewed proposals for runtime changes.
- **Dependency:** G04, G07-G08, authorized sources, scheduler recovery and compute/storage budgets.
- **Risk/priority:** P1/C. Poisoning, prompt injection, copyright/access violations and autonomous self-modification are unacceptable.
- **Minimum additive change:** provider-free ingestion of an approved local corpus into `candidate` records only; no production promotion or code/tool/policy mutation.
- **Verification:** scheduler restart, dedupe, poisoning/injection, rights, promotion denial, expiry, resource budget and global-stop tests.
- **Rollback:** stop schedule and delete/export candidate sidecar records under retention policy; existing memory remains unchanged.
- **Owning phase:** Phase 14.

### G17 — Unified Command Center and observability

- **Current status/evidence:** `PARTIAL`. Qt desktop UI, 3D Orb, dashboard, system status and basic mission status exist; unified mission/approval/evidence/cost/connector/security projections do not.
- **Target contract:** one callback-compatible spatial shell plus authenticated remote projections for missions, approvals, Founder Command, evidence, connector health/scopes/quota/spend, browser takeover, knowledge digest, security and kill switch; explicit verified/partial/unverified/blocked/simulated language.
- **Dependency:** stable G02-G16 data contracts; Cyryx design tokens and accessibility/resource budgets.
- **Risk/priority:** P2. A cinematic UI that overstates runtime truth or consumes excessive CPU/GPU undermines trust and usability.
- **Minimum additive change:** add read-only projections to the current shell; do not create a second persistence path or duplicate permanent UI shell.
- **Verification:** callback parity, accessibility, visual regression, responsive/remote auth, idle CPU/GPU, active frame-time and adaptive-quality tests.
- **Rollback:** disable new projections/shell flag and retain current `OnyxUI`/dashboard callbacks.
- **Owning phase:** Phase 15.

### G18 — Supply chain, licensing and cross-platform release proof

- **Current status/evidence:** proprietary/public release is `BLOCKED_BY_LICENSE`. `packaging/onyx.spec`, `scripts/build_release.py` and multi-host workflow are `PARTIAL`; `OPEN_SOURCE_AND_API_LICENSE_REVIEW.md` identifies source-rights, PyQt/Qt, `crypto-js`, dependency-lock, SBOM/notice and provider gates.
- **Target contract:** reproducible host-native artifacts for Windows, macOS Intel/ARM and Linux x64/ARM with exact SBOM/licenses/notices, approved binding/license path, signatures/notarization where applicable and clean-machine install/upgrade/uninstall/smoke evidence.
- **Dependency:** ownership/legal decisions, locked dependencies, exact artifact inventories, signing identities and host-native CI/runners.
- **Risk/priority:** P3 release blocker. Technical build success cannot grant redistribution rights or prove operational compatibility.
- **Minimum additive change:** make publication fail closed; generate locks/SBOM/notices for internal artifacts before resolving the final distribution path.
- **Verification:** license policy on exact artifacts, hashes/signatures, clean-machine tests, QML/plugins/browser/audio/vault checks and vulnerability review.
- **Rollback:** keep artifacts internal/unpublished; revoke a release rather than ship under unresolved rights or broken host behavior.
- **Owning phase:** Phase 16.

## Dependency order

```text
G01
  -> G02 -> G03 -> G04 -> G05 -> G06
                 |              |
                 +-> G08 -------+
                              -> G07 -> G09
                                      |-> G10
                                      |-> G11
                                      |-> G12
                                      |-> G13
                                      |-> G14
                                      |-> G15
                                      +-> G16
G02-G16 stable --------------------------> G17 -> G18
```

No connector wave should be parallelized before G02-G06 are proven. Afterward, each business domain must start with one read-only test-account/provider vertical slice and stop at its review gate before draft or mutation capability is enabled.

## Exit criteria for the gap program

The gap program is complete only when every intended capability has a truthful matrix status backed by current evidence; every high-risk action denies without exact authority; all external mutations have idempotent requests, receipts and observed-state verification; cross-workspace leakage is zero; uncertain effects reconcile before retry; the stable core remains compatible with extensions disabled; and distribution occurs only after the explicit license and platform gates close.
