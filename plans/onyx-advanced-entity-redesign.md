# Onyx advanced entity and governed operations master plan

Status: additive master plan updated on 2026-07-14. Phases 1-3 are implemented and verified; all later phases remain planned and gated.

Primary outcome: Onyx becomes a persistent, evidence-driven daily-work assistant and governed operations layer with a distinct Cyryx spatial interface, true GPU-backed 3D presence, low idle resource use, model/provider portability and explicit risk boundaries.

Source extension: `# ONYX — Master Implementation Prompt v1.0 — Governed Autonomous Operations Layer for Cyryx Labs` is incorporated here as an additive capability program. It does not authorize a rewrite or replacement of the current engine.

## Compatibility constitution — non-negotiable stable core

1. The current runtime remains the source of truth. Preserve the existing authentication, voice, tool registry and call protocol, memory, scheduler, desktop/browser control, remote dashboard, mission store/worker, permission broker, Orb bridge, packaging and UI callbacks.
2. Build outward through versioned adapters, registries, typed contracts, events and sidecar tables. Do not fork a second mission engine, permission system, memory system, tool dispatcher, model client or UI runtime.
3. Existing public functions, persisted data, tool names and default behavior remain compatible. A change requires a versioned adapter or migration, rollback path and contract/regression tests before cutover.
4. The current provider and direct-tool paths remain the default adapters until an alternative passes the same contract, security and evaluation gates. Model routing is an orchestration layer, not a replacement of `core/llm_client.py`.
5. Existing browser and native-computer actions remain available as hardened fallbacks. Official API, CLI, SDK or MCP connectors take precedence for new provider capabilities, without silently removing current control paths.
6. New capabilities are disabled by default, registered with an exact status, scoped to one workspace and exposed only when their access, license, health and tests are real.
7. New persistence is additive and namespaced. No destructive schema rewrite, global rename, credential movement or cross-workspace migration is allowed.
8. Every external mutation flows through the existing permission/audit boundary, a typed action request, exact approval digest, idempotency key, receipt and post-action verification.
9. High-impact actions remain explicitly approval-gated. Natural day-to-day operation uses risk-scoped, expiring grants and signed autonomy envelopes so harmless work does not produce an approval dialog for every step.
10. Runtime code must not claim capabilities that are mocked, inaccessible, unlicensed, platform-blocked or unverified.

### Stable contracts to preserve

- Missions: `MissionStore.create/approve/run/claim_next/heartbeat/release_lease/resolve/events` and `MissionWorker` in `core/missions.py`.
- Authorization: `authorize_model_tool`, `authorize_mission_tool`, exact request digests and audit-health fail-closed behavior in `core/permission_broker.py`.
- Execution safety: protected roots and structured built-ins in `core/mission_tools.py`; immutable source materialization in `core/approved_execution.py`.
- Model/tool flow: `core/llm_client.py`, the tool declarations/dispatch in `main.py` and `core/tool_audit.py`.
- Memory/configuration: `memory/store.py`, `memory/memory_manager.py` and `memory/config_manager.py`, extended through workspace-aware adapters rather than replaced.
- Interaction surfaces: voice/STT/TTS, `OnyxUI`, `OrbHost`, `OrbStateBridge`, `dashboard/server.py` and the authenticated dashboard protocol.
- Paths and distribution: `resource_root()`, `data_root()`, native packaging definitions and compatibility migrations.

### Capability truth vocabulary

Every row in the capability registry and matrix must use exactly one status:

- `WORKING_AND_VERIFIED`
- `WORKING_WITH_LIMITATIONS`
- `PARTIAL`
- `STUB_OR_MOCK`
- `NOT_IMPLEMENTED`
- `BLOCKED_BY_ACCESS`
- `BLOCKED_BY_LICENSE`
- `BLOCKED_BY_PLATFORM`
- `DEPRECATED`

Each row records evidence, code location, environment dependency, workspace, data/security class, owner, tests, last verification, limitations and next action.

## Phase 0 — Evidence-backed current-state audit and architecture gate

Status: next mandatory checkpoint. This phase changes documentation and runs safe diagnostics only; it does not migrate production architecture.

### Required outputs

Create and review before any Phase 4+ implementation:

1. `docs/onyx/CURRENT_STATE_AUDIT.md`
2. `docs/onyx/CAPABILITY_MATRIX.md`
3. `docs/onyx/GAP_ANALYSIS.md`
4. `docs/onyx/TARGET_ARCHITECTURE.md`
5. `docs/onyx/THREAT_MODEL.md`
6. `docs/onyx/APPROVAL_POLICY.md`
7. `docs/onyx/DATA_AND_MEMORY_BOUNDARIES.md`
8. `docs/onyx/OPEN_SOURCE_AND_API_LICENSE_REVIEW.md`
9. `docs/onyx/IMPLEMENTATION_ROADMAP.md`
10. ADRs for every material stack, persistence, connector, model-routing and UI decision.

The audit must inspect repository/branch state, runtimes and locks, UI/voice/model/tool/MCP/browser/memory/scheduler/auth/secrets/observability/test/release/document pipelines, existing integrations, Cyryx/MAAX/Lyra knowledge, TODO/dead/duplicate code, privacy and supply-chain risk. It must distinguish verified behavior from code presence or documentation claims.

### Allowed APIs and patterns

- Preserve `MissionStore.create/plan_summary/get/list/transition/approve/run/cancel/claim_next/heartbeat/release_lease/resolve/pause/events`, `normalize_mission_result`, `verify_mission_result` and `MissionWorker` from `core/missions.py`.
- Preserve `authorize`, `authorize_model_tool`, `authorize_mission_tool`, `build_request`, exact request digests and audit-health behavior from `core/permission_broker.py`.
- Preserve `_roots`, `_safe`, `_root_for`, `_open_verified` and structured `run` behavior in `core/mission_tools.py`, plus immutable source materialization/validation/execution in `core/approved_execution.py`.
- Use the existing Cyryx color tokens in `ui.py` as the canonical desktop palette and mirror them as CSS custom properties.
- Use `resource_root()` for packaged read-only visual assets and `data_root()` for migratable runtime state.
- Use a single `QQuickWidget` bridge for the first Qt Quick 3D Orb cutover: `setResizeMode(SizeRootObjectToView)`, `rootContext().setContextProperty(...)`, `setSource(QUrl.fromLocalFile(...))`.
- QML modules verified locally: `QtQuick`, `QtQuick3D`, `QtQuick3D.Particles3D`, `QtQuick3D.Effects`.
- Official references:
  - Qt Quick 3D: https://doc.qt.io/qt-6/qtquick3d-index.html
  - Scene Graph/RHI: https://doc.qt.io/qt-6/qtquick-visualcanvas-scenegraph.html
  - QQuickWidget: https://doc.qt.io/qt-6.11/qquickwidget.html
  - Particles3D: https://doc.qt.io/qt-6/qtquick3d-particles3d-qmlmodule.html
  - Qt Quick performance: https://doc.qt.io/qt-6/qtquick-performance.html

### Discovery gates

- PyQt6 6.11.0, Qt 6.11.1, QtQuick3D, Particles3D and PyInstaller hooks are installed.
- Proprietary distribution is blocked until Cyryx obtains a commercial PyQt license or completes a reviewed PySide6/LGPL migration.
- Brand fonts must not be bundled until their redistribution licenses are confirmed.
- Proprietary distribution license is established under Cyryx Labs LLC commercial terms prohibiting unauthorized commercialization without payment.
- Revalidate official provider documentation, permissions, API versions, prices, rate limits, policies and supported automation surfaces immediately before implementing each connector; the attachment's July 14, 2026 integration baseline is a starting point, not a permanent guarantee.
- Build **Argos**, Onyx's 100%-proprietary Cyryx world-intelligence component, in-house instead of integrating any third-party World Monitor. Argos reuses no external world-monitoring code/UI/assets, so it carries no third-party source/AGPL obligation; each underlying data-provider's API terms remain a separate obligation. (The previously planned third-party World Monitor is dropped.)
- Treat social, ads, email/calendar, travel and external-agent providers as `BLOCKED_BY_ACCESS` until OAuth/app review/test-account/credential requirements are satisfied.

### Anti-pattern guards

- No `QOpenGLWidget`, private `QRhi`, `QQuickFramebufferObject`, QML Canvas or thousands of QML delegates for particles.
- Do not force the OpenGL backend; let Qt RHI select D3D/Metal/Vulkan/OpenGL.
- No destructive identity replacement that discards compatibility data.
- No invented `agent_task` alias.
- No implementation wave after Phase 0 until its audit artifacts are reviewed and the minimum-change architecture is accepted.
- No evidence claim based only on a file's existence or an agent's confidence.

## Phase 1 — Identity and contract integrity

Status: `WORKING_AND_VERIFIED` in the current development tree. Preserve the completed migrations and regression coverage.

### What to implement

1. Replace every visible legacy third-party reference with Onyx/Cyryx Labs across desktop, remote, setup, permission and generated pages.
2. Introduce new primary runtime/storage names (`onyx_*`, `ONYX-DASHBOARD-v2`, Onyx certificate/profile/task names) while reading legacy names only through explicit compatibility migration.
3. Rewrite `core/prompt.txt` to use direct tools for simple tasks and `mission_create/status/run/cancel` for compound work; remove nonexistent `agent_task` instructions.
4. Replace absolute “private/local intelligence” claims with precise state labels that distinguish local tools from cloud model processing.
5. Mirror the official Cyryx palette in remote CSS and integrate the approved monolith asset after visual validation.
6. Keep font fallbacks until font licenses are confirmed.

### References to copy

- Token source and UI callbacks: `ui.py::OnyxUI`, `ui.py::OrbHost` and the module-level Cyryx palette.
- Identity/setup flow: `ui.py::OnyxUI`, `core/identity.py`.
- Real tool declarations/dispatch: `main.py::TOOL_DECLARATIONS`, `main.py::OnyxLive._execute_tool`.
- Existing model compatibility convention: `core/live_model.py`.
- Remote token blocks: `dashboard/static/app.html`, `dashboard/static/login.html`.

### Verification

- Text scan finds no visible foreign identity and permits legacy strings only in explicitly named migration constants/tests.
- Prompt-referenced tools are a subset of model-exposed declarations.
- Legacy storage/certificate/session data migrates without deletion.
- Dashboard authentication, audio worklet, upload and device login tests pass.
- Full unit suite, compile, Ruff F/E9 and diff check pass.

### Anti-pattern guards

- Do not rename one side of the browser/server crypto contract alone.
- Do not delete existing certificates, profiles, scheduler entries or credentials.
- Do not weaken permission policy to make copy claims true.

## Phase 2 — GPU Orb bridge

Status: `WORKING_AND_VERIFIED` in the current development tree, including real QML component loading, reduced-motion/minimize lifecycle and fallback behavior.

### What to implement

1. Add one packaged `qml/OnyxOrb.qml` scene using `View3D`, `SceneEnvironment`, camera, light and `ParticleSystem3D`.
2. Add an `OrbStateBridge(QObject)` exposing state, active, muted, reduced-motion and particle-budget properties with change signals.
3. Add one `QQuickWidget`-based Orb host that preserves the public methods used by `OnyxUI` and falls back to the existing `HudCanvas` if QML status is error or GPU capability is unavailable.
4. Stop all particle systems in idle/listening/muted/hidden/minimized states. Update the bridge only on state transitions; use no Python repaint timer.
5. Add adaptive quality tiers and a software/reduced-motion still mode.
6. Add QML/Quick3D resources and imports to the PyInstaller spec and package smoke test.

### References to copy

- Lifecycle and visual state behavior: `ui.py::OrbHost`, `ui.py::OnyxUI`, `core/orb_state.py::OrbStateBridge`.
- Official Qt Particles3D example and QQuickWidget signatures listed in Phase 0.

### Verification

- QML component reaches Ready state and exposes the expected root object.
- Idle has no running particle system or recurring Python repaint timer.
- State/mute/hide/minimize transitions stop and resume correctly.
- Existing UI tests pass with GPU host and forced fallback host.
- Frozen package smoke test locates QML and QtQuick3D plugins.

### Anti-pattern guards

- No infinite animation while idle.
- No multiple QQuickWidgets or duplicated CPU/GPU Orb running concurrently.
- No forced backend or private Qt API.

## Phase 3 — Persistent mission worker and verifier

Status: `WORKING_AND_VERIFIED` in the current development tree. The application-owned worker, structured evidence/postconditions, pause/cancel handling and late-result rejection must remain the single execution foundation.

### What to implement

1. Generalize `worker_once` to accept an explicit `ToolRunner` while keeping `_local_runner` as the CLI default.
2. Add an application-owned worker lifecycle using `claim_next`, lease heartbeat, bounded poll interval, clean stop and `release_lease`.
3. Add a structured result contract with status, redacted evidence, postconditions and waiting reason.
4. Verify deterministic postconditions before committing success; uncertain external effects transition to `waiting`, never automatic retry.
5. Surface active mission, current step, evidence and waiting resolution in the new contextual UI.

### References to copy

- Worker/lease protocol: `core/missions.py::MissionStore`, `worker_once`, `MissionWorker`.
- Tests: `tests/test_missions.py`.
- Tool audit trace pattern: `main.py::OnyxLive._execute_tool`, `core/tool_audit.py`.

### Verification

- Exclusive claims, heartbeats, clean shutdown, crash recovery and late-result rejection pass.
- No approved mission is broadened into a blanket tool grant.
- A failed/uncertain side effect cannot be repeated automatically.

### Anti-pattern guards

- No direct SQL from worker orchestration.
- No daemon execution of draft/awaiting missions.
- No arbitrary shell mission tool.

## Phase 4 — Trust foundation and additive domain contracts

### What to implement

1. Extend the existing mission record through backward-compatible fields/sidecar tables for `correlation_id`, `workspace_id`, definition of done, scope/exclusions, data class, allowed targets, budgets, autonomy mode/expiry, checkpoints, receipts, verification and recovery.
2. Map the richer lifecycle (`INTAKE`, `CLARIFY_OR_SCOPE`, `RESEARCH`, `PLAN`, `POLICY_CHECK`, `WAITING_FOR_APPROVAL`, `EXECUTE`, `VERIFY`, `CONFIRM`, `MONITOR`, `ADAPT`, terminal states) onto the existing durable state machine through versioned transition adapters; do not rewrite the worker/lease protocol.
3. Add typed, versioned `EvidenceRecord`, `Claim`, `ActionRequest`, `ActionReceipt`, `MemoryItem`, `EventEnvelope`, `CapabilityDescriptor` and `AutonomyEnvelope` contracts. Store redacted envelopes in the append-only mission/audit ledger and artifacts by reference.
4. Add a workspace registry with separate credential aliases, policy, retention, classification, memory namespace/filter, artifact root, browser profile, audit scope and export/delete controls for Cyryx, external/client, professional and personal contexts.
5. Add a capability/operator registry. Operator Cells are role profiles with declared tools, data access, model requirements, budget, evaluation and handoff contracts; they reuse the current orchestrator and do not create needless agent fan-out.
6. Add an emergency kill switch that blocks new mutations, cancels/reconciles active work and revokes scoped sessions where supported.

### References to copy

- Current state/lease/events: `core/missions.py` and `docs/MISSIONS.md`.
- Authorization/digest: `core/permission_broker.py` and `core/tool_audit.py`.
- Persistence boundaries: `memory/memory_manager.py`, `memory/config_manager.py`, `core/paths.py`.
- The attached master prompt sections 3, 5-7, 18-21 and Release 1.

### Verification

- Migration round-trip preserves all legacy missions, events, tools, credentials and memory; old clients still pass contract tests.
- Every transition is validated, append-only and restart-safe; invalid/late transitions fail closed.
- Cross-workspace retrieval, tool, browser-profile, credential and artifact leakage tests return zero unauthorized results.
- Secrets and sensitive fields never enter model context, ordinary logs, screenshots or fixtures.
- Existing Phase 1-3 and full regression suites remain green.

### Anti-pattern guards

- No second database or event ledger as a shortcut around current storage.
- No vector similarity as authority; workspace, sensitivity, validity and freshness filters run before ranking.
- No self-modifying prompts/tools/policies/code outside a reviewed proposal and normal release path.

## Phase 5 — Risk-scoped grants, approval inbox and Capability Nexus

### What to implement

1. Add four autonomy modes: Observe, Assist, Supervised Execute and Bounded Delegate. Mode D requires a signed, expiring `AutonomyEnvelope` containing exact workspace, mission, allowed/forbidden targets/actions, budget, tests, notifications, approval policy and stop conditions.
2. Add immutable, expiring, use-limited session grants bound to session, workspace, tool/action, roots/destinations, risk, cost and approval digest. Material payload or target changes invalidate the grant.
3. Keep purchases, billing, ad enablement/spend expansion, public/legal/crisis/sensitive communication, production deploy/destructive migration, protected-branch merge, sensitive export/delete, auth/secret/role changes and unverifiable actions explicitly gated.
4. Add the approval inbox, grant inspector/revoke flow and calm batch approvals so routine read/draft work is natural without weakening high-risk controls.
5. Add a normalized Capability Nexus connector interface for auth refresh, discovery, reads, drafts, mutations, pagination, backoff, webhook/polling, dry run, idempotency, receipts, health/scopes, quotas/cost and degraded mode.
6. Prove the connector contract with one low-risk provider/test account before adding a second. Credentials stay in the OS vault; connector records store aliases only.

### References to copy

- Current permission boundary: `core/permission_broker.py`.
- Current model/tool dispatch: `main.py`, `core/llm_client.py`, `core/tool_audit.py`.
- Current vault helpers: `core/credentials.py`.
- Attached master prompt sections 6.4, 20-21 and Releases 1/9.

### Verification

- Grant expiry/use/logout/revoke/audit-health and scope-change tests pass.
- Unknown tools/actions/scopes fail closed; connector health reports real API/version/scopes/quota/degraded mode.
- Duplicate or uncertain external responses reconcile before retry; every mutation yields request, receipt and observed final state.
- Approval prompts are suppressed only when an exact valid grant/envelope covers the action.

### Anti-pattern guards

- No generic `connector_execute`, blanket owner autonomy or browser workaround for missing scopes.
- No tokens, cookies, message bodies or payment/identity data in mission events, memory or logs.

## Phase 6 — Model router, MCP and external-agent adapters

### What to implement

1. Wrap the current model client as the first versioned provider adapter, preserving its behavior. Add a capability registry for modality, structured output, tool reliability, context, privacy/residency, latency, cost, availability and evaluation history.
2. Add policy-aware routing and explicit fallback chains. Workspace/privacy rules override price or convenience; sensitive data may not silently move to a less trusted provider.
3. Add MCP client/server boundaries through the Capability Nexus and record server identity, tool schemas, authorization, transport health and provenance.
4. Add `ExternalAgentAdapter` for official API/CLI/SDK/MCP surfaces first, with browser UI only as an authorized fallback. It submits mission packets, records provider/session IDs, monitors without busy loops, collects artifacts/diffs/tests/errors, supports follow-up/cancel and reconciles results into the existing mission ledger.
5. Add versioned Operator Cell profiles, beginning with independent verifier and software roles; dispatch only the minimum roles needed.

### References and verification

- Preserve `core/llm_client.py`, `main.py` tool declarations/dispatch, current browser/computer actions and `MissionWorker` as defaults/fallbacks.
- Use official provider/MCP/CLI documentation revalidated at implementation time.
- Contract tests must prove equivalent tool schemas, redaction, provider outage/fallback behavior, cost ceilings and independent result verification.

### Anti-pattern guards

- No provider name in core domain models; no provider fallback that changes privacy class.
- No browser automation masquerading as a private API; no needless multi-agent fan-out.

## Phase 7 — Company Graph, layered memory and Founder Command

### What to implement

1. Build the Cyryx Company Graph from authorized strategy, governance, PRDs, repositories/issues/PRs/releases/tests, roadmaps, meetings, approved analytics/research and MAAX/Lyra/Cyryx artifacts.
2. Represent approved fact, current status, proposal, rejected/superseded decision, hypothesis, risk, dependency, metric and evidence separately. Every status includes source, owner, verification time, confidence, blocker, milestone and definition of done.
3. Extend memory through adapters into session, episodic mission, semantic institutional, decision, procedural, preference and temporal-status layers. Add dedupe/entity resolution, contradiction, supersession, freshness, correction, retention/export/delete and poisoning defenses.
4. Produce Daily Founder Brief, weekly review, portfolio, blockers/dependencies, decision/opportunity/risk queues, change delta and evidence-ranked top actions. Never invent revenue, traction, customers, runway or validation.
5. Add document ingestion for PDF/DOCX/Markdown/text/spreadsheet/presentation/image/OCR/code with granular citations, version comparison, requirement/decision extraction and render/visual QA.

### References and verification

- Extend `memory/memory_manager.py`, `memory/config_manager.py`, existing code/document actions and mission evidence contracts.
- Groundedness, citation, stale-status, contradiction, malicious-document, workspace-isolation and source-deletion tests must pass.
- Founder Brief claims must link to evidence and distinguish known/inferred/unknown with last verification.

### Anti-pattern guards

- No global vector index without hard workspace filters; no completion inferred from a file or agent statement.
- Treat documents, email and web content as untrusted evidence, never runtime instructions.

## Phase 8 — Executive office connectors and daily operations

### What to implement

1. Add connectors in the order calendar read/brief/draft/create, email search/read/draft/send, tasks/notifications, then Drive/OneDrive and Office; prove one provider before generalizing.
2. Support inbox/message triage, deadlines/commitments/follow-ups, context-preserving drafts, recipient resolution, calendar conflicts/availability/prep/travel-aware scheduling, task/review cadence and meeting decision/action reconciliation.
3. Route notifications by urgency, quiet hours, workspace and device. Show the real sender/account, recipient, workspace and consequential payload before execution.

### Verification and guards

- Use official provider docs, least OAuth scopes, sandbox/test accounts and contract/E2E tests.
- Reading/drafting may use workspace policy; sends, external invites, cancellations, shared-calendar changes and confidential disclosure require an exact grant or explicit approval.
- No ambiguous recipient send, no cross-workspace contacts/context and no message body in general memory/audit.

## Phase 9 — Intelligence and opportunity radar

### What to implement

1. Add primary/official-source-first ingestion for geopolitics, finance/macro, AI/technology/cyber, startups/markets, API changes, creator economy and Cyryx-relevant opportunities.
2. Record publication time and event time; deduplicate recycled stories; separate fact, inference, scenario and recommendation; corroborate consequential claims where possible.
3. Add transparent opportunity scoring for pain/economic cost, urgency, buyer/payability, timing, competition, Cyryx advantage, time to MVP/revenue, complexity, distribution, moat, legal/platform risk and evidence confidence.
4. Build **Argos**, a 100%-proprietary Cyryx Labs world-intelligence connector (the in-house replacement for the dropped third-party World Monitor), as an isolated internal component with upstream/source-health attribution.

### Verification and guards

- Citation correctness, temporal freshness, source health, duplicate-story and conflicting-claim evaluations pass.
- Argos is a proprietary Cyryx build and reuses none of any third-party World Monitor's UI/assets/source; each underlying data-provider API stays within its own terms.
- Never turn geopolitical/financial headlines into autonomous trading actions.

## Phase 10 — Social organic operating system

### What to implement

1. Start with one official provider and test account after OAuth/app-review approval. Add workspace/account inventory and separate brand passports for Cyryx Labs, MAAX Studio, Lyra and other authorized brands.
2. Build evidence-backed audience/trend research, 30/60/90 strategy, funnel/KPI tree, editorial calendar and experiment ledger.
3. Build the content pipeline: research packet, claim validation, channel copy, original/authorized asset provenance, carousel/video production specs, accessibility, brand/policy review, preview/approval, schedule/publish, live verification and analytics learning.
4. Add community monitoring/replies only within official API scope, with narrow reversible rules and escalation for reputation, legal, security, crisis, partnership and sales signals.

### Verification and guards

- First publish per account is explicitly approved; later publishes require an approved calendar/policy window, idempotency and verified platform post ID.
- Never buy followers, run bots/follow-unfollow/spam, use fake personas, scrape private data, evade policy, copy competitors or fabricate testimonials/stats/logos.
- Do not claim cross-platform metric equivalence or experiment winners from inadequate samples.

## Phase 11 — Browser/computer control and Project Autopilot

### What to implement

1. Harden existing native/browser actions instead of replacing them. Add Playwright/MCP DOM/accessibility-first control, vision fallback, headed preview, action cursor, pause/takeover/resume/emergency stop and isolated profiles.
2. Add target/domain/download allowlists, pre/post mutation evidence, foreground/window/element verification, DPI resilience, clipboard classification, screenshot redaction and UI-drift/dialog/domain-change fail-closed behavior.
3. Implement Away Mode only inside a signed Autonomy Envelope. Software missions audit repository/working tree, plan/risk, isolate work, implement incrementally, run required gates, review diffs/artifacts, use an independent verifier and return a checkpoint/draft PR.

### Verification and guards

- Test wrong targets, drift, dialogs, takeover, MFA/CAPTCHA/account lockout, restart/recovery, budget exhaustion and unrelated working-tree changes.
- Never steal cookies, capture OTPs, weaken MFA, automate password managers/banking/security settings/secrets, merge/deploy/delete/rotate/incur spend without exact authorization.

## Phase 12 — Paid Growth command

### What to implement

1. Start read-only with Meta/Google reporting after official access. Audit conversion definitions, tags/events, consent, attribution, landing pages, UTMs, CRM feedback and test conversions before optimization.
2. Produce campaign architecture, creative/message matrix, exclusions, economic hypothesis, stop-loss/scaling policy, measurement limits, estimated learning window and approval record.
3. Progress from report to draft change set, create-paused, approval-gated launch and bounded optimization. Enforce hard daily/total spend limits in runtime policy and preserve before/after state.

### Verification and guards

- Use test accounts/sandboxes; real spend is never an automated fixture.
- Billing, enablement, spend-cap removal/increase, material targeting/geography/conversion changes require exact approval or pre-approved bound.
- No unrestricted scaling or ROAS claim without verified cost and conversion/revenue data.

## Phase 13 — Travel intelligence

### What to implement

1. Keep consented traveler preferences scoped and store sensitive identity/payment data only in an encrypted vault or user-entered checkout.
2. Use authorized inventory such as Amadeus plus permitted comparison, ranking price/fees, duration, stops/risk, timing, airports, baggage/seat, terms, reliability and loyalty value; show cheapest/fastest/best trade-offs.
3. Automate search/shortlist, then reprice and verify availability before an approval-bound booking request containing exact passenger/airport/date/time-zone/cabin/baggage/terms/total/currency.

### Verification and guards

- Flight purchase always requires final confirmation and a verified booking reference/receipt.
- Never claim exhaustive coverage; never retry uncertain payment before provider reconciliation.

## Phase 14 — Nighttime Knowledge Refinery

### What to implement

1. Schedule a bounded 23:00-06:00 local pipeline: discover, filter, deduplicate, source-score, lawfully acquire, parse, extract/cross-check, synthesize/evaluate, create candidate memory, promotion gate and morning digest.
2. Add source allow/deny/diversity policy and limits for domains, pages, video duration, tokens, storage, cost, CPU/GPU and bandwidth, with quiet hours and global stop.
3. Keep new facts in `candidate`; consequential facts need corroboration/authoritative primary source; preserve conflicts; expire time-sensitive claims; keep low-confidence material as research.
4. Turn prompt/tool/policy/code/skill changes into reviewed proposals or pull requests only.

### Verification and guards

- Scheduler restart, dedupe, poisoning/injection, copyright/authorization, promotion, expiration, cost and kill-switch tests pass.
- Never bypass paywalls/DRM/access controls or store substitute copies of protected works; never autonomously deploy, broaden permissions, add credentials or retrain production models.

## Phase 15 — Command Center, spatial shell and observability

### What to implement

1. Evolve the transitional QQuickWidget into one Qt Quick/QQuickView shell only after callback parity. The active mission is primary; reveal context, files, evidence, tools and telemetry when relevant.
2. Add mission queue/live state, approval inbox, Founder Brief/portfolio, intelligence/opportunities, social studio/calendar, ads measurement, browser activity/takeover, learning digest, connector/scope/quota/spend health, evidence ledger, security and kill switch.
3. Preserve voice and add configurable wake/push-to-talk, streaming/interruptible interaction where supported, transcript synchronization, explicit state language, quiet/away modes and accessible keyboard/reduced-motion operation.
4. Track workspace/mission/operator/connector/model state, duration, failures/retries, calls/quotas, token/compute/media/external cost, approval wait, takeover, verification/citation/retrieval/reconciliation quality and domain outcomes.

### Verification and guards

- Functional parity, accessibility, visual regression, responsive/remote, idle CPU/GPU, active frame-time and adaptive-quality tests pass.
- Preserve Cyryx Onyx/Obsidian, steel/silver and controlled teal tokens; do not copy third-party interfaces or retain duplicate shells indefinitely.
- High-cost routing must demonstrate evaluated quality benefit; never save cost by weakening privacy or verification.

## Phase 16 — Hardening and cross-platform release

### What to implement

1. Complete adversarial groundedness/injection/workspace/secrets/idempotency/uncertain-response tests, connector contract/E2E suites, chaos/recovery/load/long-running mission tests and security review.
2. Add SBOM, dependency/license review, signed artifacts where feasible, backup/recovery/retention/export/delete runbooks, incident/kill-switch procedures and capability/runbook documentation.
3. Resolve the proprietary Qt binding license gate, font/media licenses and every provider's terms before release.
4. Verify Windows, macOS Intel/ARM and Linux x64/ARM packages, signing/notarization, clean-machine install/upgrade/uninstall and QML/plugin resources.

### Verification and guards

- No proprietary release under an unresolved PyQt/PySide or third-party license.
- No capability exits a blocked/partial status without real auth, failure/retry/cancel/rate-limit behavior, observability, docs and proportional E2E proof.

## Release mapping and dependency order

| Source release | Integrated phase(s) | Entry gate |
|---|---|---|
| Trust foundation | 4-6 | Phase 0 reviewed; legacy contracts frozen by tests |
| Company Command | 7-8 | Workspace isolation and typed evidence live |
| Intelligence | 9 | Source/citation evaluations; Argos (proprietary) connector built in-house or omitted |
| Social Organic | 10 | One official test account and brand passport |
| Browser and Project Autopilot | 11 | Autonomy Envelope, redaction and kill switch live |
| Paid Growth | 12 | Measurement verified; hard spend policy live |
| Travel | 13 | Licensed inventory and payment-reconciliation design |
| Knowledge Refinery | 14 | Candidate-memory promotion and resource limits live |
| Command Center | 15 | Stable data contracts and existing callback parity |
| Hardening/release | 16 | All intended capabilities truthfully classified |

Do not build every connector simultaneously. At each phase: prove one vertical slice with a test provider/account, update the capability matrix, preserve the previous release's regression suite, record an ADR and stop at the review gate before expanding.

## Final verification

- Full unit, contract, integration, evaluation and browser tests pass; no real post, spend, purchase, production mutation or sensitive message is an automated fixture.
- `ruff --select F,E9`, compileall, dependency/security/license audit, SBOM and diff check pass.
- Grep for prohibited identity/contracts, secrets and private/deprecated rendering APIs.
- Verify package resources, QML imports and native clean-machine smoke tests.
- Confirm every UI claim maps to actual runtime behavior and one truth state: verified, partially verified, unverified, blocked or simulated.
- Confirm 100% of high-risk actions fail without valid approval; all external mutations create request/receipt and observed-state verification; zero unauthorized cross-workspace retrievals; restart/retry tests prevent or reconcile duplicate actions.
- Every completed release includes scope/definition of done, ADRs, threat update, migrations, schemas, code/tests/evals, capability-matrix delta, UI evidence, cost impact, security/license findings, runbook/rollback and exact limitations.

## First safe execution checkpoint

The next implementation turn performs Phase 0 only: produce the ten evidence-backed audit/architecture artifacts, run safe current-state tests/checks, classify every capability and return the minimum-change proposal. No Phase 4+ migration starts until that checkpoint is reviewed. Phases 1-3 remain untouched except for defect fixes covered by their existing contracts and tests.
