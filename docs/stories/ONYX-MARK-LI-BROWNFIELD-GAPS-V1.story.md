# Story ONYX-MARK-LI-BROWNFIELD-GAPS-V1 — Governed Mark-LI Brownfield Capability Gaps

**Status:** Ready for Review — local capability implementation and canonical relevant gate PASS; live provider activation and release remain separate external gates
**Epic:** Brownfield parity gaps confirmed by the prior Mark-LI audit
**Source basis:** Owner request dated 2026-08-23 and the previously completed Mark-LI audit only. No additional product behavior is implied.

## Executor Assignment

```yaml
executor: "@dev"
quality_gate: "@architect"
quality_gate_tools:
  - architecture-boundary-review
  - security-and-governance-review
  - automated-tests
```

## Story

**As the** Cyryx Labs owner,  
**I want** the confirmed Mark-LI gaps implemented through Onyx's existing governed, CLI-first runtime,  
**so that** enhanced live audio, isolated plugins, opted-in clipboard assistance, governed personalization, wellness counters, content generation, and controlled social upload are useful without bypassing consent, provider, audit, or reconciliation boundaries.

## Scope and System Flow

This is one brownfield integration story covering only these confirmed gaps:

1. enhanced Gemini Live audio with affective/proactive behavior and a truthful fallback;
2. isolated plugin runtime and plugin manager;
3. clipboard intelligence, explicitly opt-in;
4. governed personalization;
5. calorie counter;
6. exercise counter;
7. caption generation; and
8. governed social-media upload.

The delivery order is **CLI first → observability second → UI third**. Each capability must be operable and verifiable through a CLI contract before any projection or UI control is considered complete. Existing Onyx mission, permission, workspace, credential, audit, action-request/receipt, and reconciliation authorities must be extended; this story must not create a parallel authority plane.

### Owner-Mandated Layout Freeze — 2026-09-01

The currently accepted Onyx layout is immutable for this capability-expansion story. Implementation may add or extend backend, CLI, connector, broker, observability, and governed runtime capabilities, but it must not change the accepted composition, humanoid, palette, positions, typography, controls, visual effects, motion behavior, voice behavior, or interaction layout. No new capability needs a UI projection to be complete. The V40 HUD visual/runtime source set remains the presentation authority: visual artifacts are SHA-256 bound and the UI host is compared to its accepted packaged source after newline normalization, so a content change fails while a CRLF/LF-only normalization is not misreported as layout drift.

`accumulated-context.md` was searched for as required by the story process but is not present in this checkout or the containing workspace at draft time. Cross-story coherence therefore comes from the owner-supplied prior audit boundary and the current Onyx normative documents summarized below; absence of that file must not be filled with invented requirements.

## Acceptance Criteria

1. **CLI-first capability surface.** A documented CLI surface can discover status/configuration and exercise a safe test or preview for every in-scope capability. CLI output is machine-readable, returns non-zero on rejected/failed operations, distinguishes `disabled`, `unavailable`, `degraded`, `preview`, `approved`, `dispatched`, `unknown`, `reconciling`, and `verified` where applicable, and exposes no secret or unredacted sensitive content. No capability is accepted solely from UI behavior.

2. **Enhanced Gemini Live audio.** With enhanced audio explicitly enabled and a supported Gemini Live session available, the adapter accepts affective context and bounded proactive cues without allowing model-produced affect or initiative to grant authority or dispatch tools. The host records the selected mode and redacted reason. If the enhanced mode/provider is unsupported, unavailable, times out before session establishment, or is disabled, Onyx falls back to the existing approved audio path or a no-audio degraded state according to configuration, reports the fallback truthfully, and does not silently cross-route modality, credentials, or policy. Deterministic tests cover supported, disabled, unsupported, pre-session failure, mid-session failure, cancellation, and fallback-loop prevention.

3. **Isolated plugin runtime and manager.** Plugins are installed, inspected, enabled, disabled, updated, and removed only through a host-owned plugin manager. Execution occurs outside the Onyx host process in an isolated runtime with a versioned manifest, explicit capability allowlist, workspace binding, resource/time limits, authenticated IPC, sanitized environment, no inherited secrets, and fail-closed behavior for unknown manifest fields, permissions, protocol versions, or runtime health. A plugin cannot call host tools, network, filesystem, clipboard, credentials, publication, or other plugins except through an authorized brokered capability. Crash, hang, malformed response, attempted escape, revocation, and restart recovery are observable and cannot crash or widen authority in Onyx.

4. **Plugin provenance, licensing, and clean-room evidence.** The manager records plugin identity, version, source, content digest, license metadata, requested capabilities, approval decision, and lifecycle events. No Mark-LI source, artifact, package, fixture, prompt, or generated derivative may enter the implementation workspace, dependency graph, test corpus, or release artifact; no code from Mark-LI or another CC BY-NC source is copied, translated, vendored, or mechanically derived. Before implementation, contributors record a clean-room declaration that they are implementing only from this story and Onyx-owned normative contracts, not from Mark-LI source. Before acceptance, an independent reviewer reconciles: (a) a per-file provenance ledger for all added dependencies and substantive new files, (b) dependency/license inventory and prohibited-source scan results, and (c) the final diff and packaged-source inventory. Any unknown origin, incompatible license, unavailable review evidence, or contributor exposure to Mark-LI implementation source fails this AC and blocks merge/release; a string scan alone is not sufficient evidence.

5. **Clipboard intelligence is opt-in and bounded.** Clipboard observation and analysis are default-off and require an explicit owner opt-in that states scope and retention. When off, Onyx neither reads, polls, subscribes to, persists, embeds, logs, nor sends clipboard content. When on, processing is local by default, bounded to the active workspace/session and declared content classes, ignores unsupported/oversized/binary/secret-like content, provides pause/revoke/clear controls, and never promotes content to memory or sends it to a provider without a separate governed decision. Tests verify off-state zero reads, revocation, workspace isolation, redaction, retention expiry, and no feedback loop from Onyx's own clipboard writes.

6. **Governed personalization.** Personalization uses inspectable, editable, revocable records with source/provenance, workspace/user scope, sensitivity, validity/freshness, and retention. Inference is visibly distinguished from owner-confirmed preference; inferred data cannot grant authority, lower risk, select a new external account, or override an explicit instruction. Personalization is default-off for sensitive categories and cross-workspace use, supports export/delete, and fails closed when scope or provenance is missing.

7. **Calorie counter.** The CLI can create, list, correct, and remove timestamped calorie entries within an explicit user/workspace scope and produce deterministic daily totals. Inputs are validated and bounded; units and timezone are explicit; duplicates can be prevented through an idempotency key. The feature is framed as user-entered tracking, not medical diagnosis or verified nutrition advice, and does not infer calories from clipboard/audio/content unless that source is separately opted in and the resulting entry is previewed and confirmed.

8. **Exercise counter.** The CLI can create, list, correct, and remove timestamped exercise entries and produce deterministic totals using explicit activity, count/duration/unit, and timezone. Inputs are validated and bounded, retries are idempotent, and uncertain sensor/model-derived values remain drafts until confirmed. The feature makes no medical, fitness-outcome, or device-certification claim.

9. **Caption generation.** Given owner-authorized inputs, the CLI produces a local draft/preview containing the caption, target platform/profile intent, source/provenance references, and validation warnings. Generation performs no upload or publication, does not fabricate claims or evidence, does not leak secrets/restricted data, and remains usable independently of social connector availability. Re-running with the same normalized request can produce or reference a stable request identity for downstream idempotency.

10. **Governed social-media upload.** External upload/publication is default-off and separated from caption generation. Before any provider mutation, Onyx creates a preview showing the exact account/channel, media, material caption, disclosures, expected effect, and connector; obtains explicit owner consent bound to the normalized payload/target digest immediately before dispatch; and uses an official connector/API when one is available and authorized. Browser or non-official fallback is a separately declared, explicitly approved capability and cannot masquerade as an official connector.

11. **Idempotency, receipt, and reconciliation for social effects.** Each approved upload has a stable idempotency key and one dispatch boundary, captures an `ActionRequest` and provider `ActionReceipt` (including provider request/content identifier when returned), observes provider state, and marks success only after verification. Timeout or ambiguous post-dispatch outcome becomes `unknown/reconciling`; Onyx reconciles before retry and never blindly republishes. Payload, account, media, consent, or target drift invalidates approval and requires a new preview and explicit consent.

12. **Security and privacy boundary.** All new capabilities carry explicit workspace and principal/session context; unknown or missing identity, policy, scope, target, provider outcome, audit health, or data classification fails closed. Secrets never enter model context, plugin environment, clipboard records, wellness records, captions, ordinary logs, receipts, or artifacts. Kill/revoke prevents new work and places ambiguous external effects into reconciliation. Data at rest follows existing Onyx storage and retention authorities.

13. **Observability and evidence.** Host-owned, redacted events correlate capability, mission/session, workspace, decision, dispatch, receipt, fallback/degradation, and final verification without storing raw sensitive payloads. Status projections are derived from the same authoritative records as the CLI. Evidence demonstrates default-off behavior, compatibility with existing behavior when flags are off, restart handling, and rollback by disabling each capability independently.

14. **Testing and regression gate.** Unit, contract, integration, failure-injection, and security tests cover every criterion above, including negative authorization paths, cross-workspace attempts, plugin isolation/termination, opt-out zero-read behavior, audio fallback, counter idempotency, consent drift, duplicate-publication prevention, ambiguous provider outcomes, reconciliation, and secret/log scanning. Existing relevant mission, permission, credential, audio, memory, audit, dashboard, packaging, and regression tests remain green. No release/publication claim is made from mocks alone; live provider evidence, when access exists, uses a designated test account and a reversible/non-public target where supported.

15. **Documentation and decision record.** The implementation updates the relevant capability/status and operator documentation and creates and accepts the planned ADR before the story can move to implementation review or Done. The ADR records: reuse of the single Onyx authority plane; plugin isolation boundary; enhanced-audio fallback semantics; clipboard/personalization privacy defaults; wellness-data limits; and the preview → explicit consent → official connector → idempotency → receipt → observation/reconciliation publication lifecycle.

## Security Constraints

- Default deny/default off for plugin execution, clipboard observation, sensitive personalization, enhanced proactive audio, and social mutation.
- The model, affect signal, proactive cue, plugin, clipboard content, generated caption, memory, or provider response is never a principal and cannot approve its own action.
- No in-process third-party plugin execution and no ambient authority, inherited credential, unrestricted filesystem/network access, or direct access to the permission/audit stores.
- Exact workspace, account/channel, payload/media digest, connector, consent, idempotency key, and expiry binding for external mutation.
- Preview is not approval; approval is not success; a receipt is not verification; ambiguous outcomes require reconciliation.
- Official provider connector/API is preferred whenever available; any fallback is explicit, separately consented, observable, and policy-bound.
- Clipboard and personalization data minimization, redaction, bounded retention, export/delete, revocation, and no cross-workspace fallback.
- Calorie/exercise data is private user-entered tracking and must not be represented as diagnosis, medical advice, device certification, or validated health outcome.
- No copying or derivative implementation from CC BY-NC Mark-LI code. Concepts named in the audit/request are requirements only; implementation and tests must be original or use provenance-recorded compatible dependencies.
- Capability expansion must preserve the accepted V40 HUD presentation. Visual artifacts remain byte-bound; newline-only host normalization is nonvisual. No visual artifact, layout, humanoid, palette, animation, voice behavior, or existing interaction may be changed by this story.
- Unknown schema, capability, scope, target, plugin state, provider state, or audit integrity fails closed. Kill/revoke is effective before dispatch and does not erase evidence needed to reconcile an already-ambiguous external effect.

## Tasks / Subtasks

- [x] **Slice 0 — Brownfield contracts and ADR** (AC: 1, 12, 13, 15)
  - [x] Inventory and reuse the existing mission, workspace, permission, credential, audit, action-request/receipt, memory, audio, and connector authorities; document exact extension points without creating parallel stores or dispatchers.
  - [x] Create the planned ADR and define versioned CLI contracts, closed status vocabulary, feature flags/default-off behavior, event schema, rollback, and compatibility tests.
  - [x] Record the contributor clean-room declarations and the review procedure required by AC 4; no Mark-LI implementation source was fetched, mounted, inspected, or imported during implementation.
  - [x] Add characterization tests proving flags-off behavior remains unchanged.

- [x] **Slice 1 — Enhanced Gemini Live audio** (AC: 1, 2, 12, 13)
  - [x] Add configuration/status/safe-test surfaces for affective/proactive mode and fallback state.
  - [x] Implement host-bounded affect/proactivity inputs and explicit fallback/degradation semantics without granting tool authority or silent modality cross-routing.
  - [x] Add deterministic adapter, cancellation, failure-injection, and fallback-loop tests.

- [x] **Slice 2 — Isolated plugin runtime foundation** (AC: 1, 3, 4, 12, 13)
  - [x] Define versioned plugin manifest/protocol, capability requests, workspace binding, authenticated IPC, resource limits, and sanitized process launch.
  - [x] Broker every host interaction through existing permission/audit boundaries and fail closed on unknowns.
  - [x] Require a fresh command-bound attestation from an injected native sandbox before launch; test missing/forged attestations, attempted escape, malformed IPC, crash/hang, revocation, restart, secret inheritance, and cross-workspace denial. A production native-sandbox adapter remains an external prerequisite.
  - [x] Add the connector-neutral governed capability-host foundation: closed capability/operation registry, exact principal/workspace/session-generation/argument/policy bindings, audit-health gate, binding revoke, and monotonic participant kill receipts with explicit uncertainty. No connector, router, or `main.py` integration is included.

- [x] **Slice 3 — Plugin manager lifecycle** (AC: 1, 3, 4, 13)
  - [x] Add CLI discover/inspect/install/enable/disable/update/remove/status operations with provenance, digest, license, requested-capability, and lifecycle records.
  - [x] Require explicit review for new or widened capabilities and prove disable/remove leaves no executable orphan or widened grant.
  - [x] Produce the AC 4 per-file provenance ledger, dependency/license inventory, prohibited-source review, final diff review, and scoped packaged-source inventory.

- [x] **Slice 4 — Clipboard intelligence opt-in** (AC: 1, 5, 12, 13)
  - [x] Add CLI opt-in/status/pause/revoke/clear and bounded analysis preview surfaces.
  - [x] Enforce off-state zero reads, local-first processing, content/size/sensitivity filters, retention, workspace isolation, and separate consent for memory/provider use.
  - [x] Test zero-read, revocation races, self-write loops, unsupported data, secret redaction, expiry, restart behavior, and absence of raw clipboard text in durable SQLite/WAL/SHM storage.

- [x] **Slice 5 — Governed personalization** (AC: 1, 6, 12, 13)
  - [x] Add CLI inspect/confirm/edit/revoke/export/delete operations and provenance/scope/sensitivity/freshness contracts.
  - [x] Separate inferred from owner-confirmed preferences and prohibit authority/risk/account changes from personalization.
  - [x] Test missing provenance, sensitive defaults, conflicts, expiry, deletion, and cross-workspace denial.

- [x] **Slice 6 — Calorie and exercise counters** (AC: 1, 7, 8, 12, 13)
  - [x] Implement CLI create/list/correct/remove/total contracts with explicit units, timestamps/timezone, validation, privacy scope, and idempotency.
  - [x] Keep model/sensor-derived values as previews until confirmed and add non-medical limitation messaging.
  - [x] Test duplicate retries, corrections, timezone boundaries, invalid/oversized values, retention/deletion, and isolation.
  - [x] Add an original, camera-frame-free repetition estimator that consumes only the normalized signal from the existing opted-in camera stream, retains no image/identity data, and materializes estimates only as owner-confirmable drafts.
  - [x] Add deterministic hysteresis, confidence, calibration, cancellation, and false-cycle tests plus a CLI-safe sequence preview; physical-camera calibration remains a separate acceptance gate.

- [x] **Slice 7 — Caption draft generation** (AC: 1, 9, 12, 13)
  - [x] Add a provider-independent CLI draft/preview artifact with target intent, provenance, warnings, redaction, and stable normalized request identity.
  - [x] Validate that caption generation has no upload/publish side effect and cannot fabricate evidence-backed claims.
  - [x] Test sensitive input handling, unsupported media references, deterministic request identity, and connector-unavailable operation.

- [x] **Slice 8 — Governed social upload vertical slice** (AC: 1, 10, 11, 12, 13)
  - [x] Implement preview and exact explicit-consent binding before one brokered dispatch through an official connector when available.
  - [x] Implement durable idempotency, request/receipt persistence, provider-state observation, unknown outcome, reconciliation, retry safety, and drift invalidation.
  - [x] Test duplicate attempts, crash/restart races, timeout before/after dispatch, altered caption/media/account, revoked consent, unofficial fallback declaration, and verified final state. Live mutation remains unavailable until an official authorized adapter is supplied.
  - [x] Materialize bounded local video assets as digest/size/MIME-bound dispatch leases so the exact video is covered by preview, consent, idempotency, and drift checks without persisting a raw local path in the publication ledger.
  - [x] Add CLI video-asset inspection and negative tests for unsupported type, oversized input, symlink/path drift, post-consent mutation, expired lease, missing official adapter, and restart/reconciliation behavior.

- [x] **Slice 9 — Observability, projections, docs, and full gate** (AC: 1–15)
  - [x] Produce redacted correlated status/events backed by the same authority records; optional UI projections are not required for this CLI-first slice.
  - [x] Update capability/status/operator/security/license documentation and the ADR with implemented file/contract truth.
  - [x] Bind capability expansion to the immutable V40 HUD acceptance and fail the focused regression gate on any accepted-layout drift.
  - [x] Run targeted and full relevant regression/security gates; attach evidence and reconcile the final File List before moving the story beyond implementation review.

## Dev Notes

### Brownfield Authorities to Preserve

- `docs/onyx/APPROVAL_POLICY.md#request-lifecycle`: canonicalize exact scope, authorize, dispatch once, record receipt, observe final state, and reconcile unknown outcomes.
- `docs/onyx/APPROVAL_POLICY.md#always-require-explicit-approval`: public statements/publication remain explicit-approval actions.
- `docs/onyx/TARGET_ARCHITECTURE.md#capability-nexus`: prefer official API/CLI/SDK/MCP and expose browser fallback as a distinct capability; keep connectors disabled until proven.
- `docs/onyx/TARGET_ARCHITECTURE.md#model-router-and-operator-cells`: preserve Gemini Live modality semantics and avoid silent cross-routing.
- `docs/onyx/TARGET_ARCHITECTURE.md#architectural-invariants`: one mission engine, one host permission boundary, no self-granted authority, and no completion without observed evidence.
- `docs/onyx/OPEN_SOURCE_AND_API_LICENSE_REVIEW.md`: dependency/source rights remain an explicit release gate; this story additionally forbids copying or deriving code from CC BY-NC Mark-LI sources.
- `docs/stories/ONYX-VOICE-SESSION-AUTHORITY-V1.story.md#owner-decisions-2026-08-19-explicit`: publishing remains always explicit even inside a live voice-opened work envelope.

### Assumptions and Explicit Non-Requirements

- The eight named gaps are the complete product scope for this story. Exact UX styling, calorie databases, wearable/device integrations, automatic activity recognition, social-platform list, scheduling, analytics, and autonomous posting are not authorized by the request and are out of scope unless separately approved.
- “Affective” means consuming provider-supported affective context to adapt the session; it is not emotion diagnosis. “Proactive” means bounded host-policy cues during an active session; it is not autonomous external action.
- “Social media upload” includes the governed upload/publication mutation described in AC 10–11. It does not permit unattended posting or broad account grants.
- Live-provider activation depends on owner-controlled credentials, scopes, provider availability, and test-account access. The implementation must remain truthfully disabled/degraded when those are absent.

### Testing

- Follow existing Onyx test locations and patterns under `tests/`; add unit tests for pure contracts and integration tests at existing host boundaries.
- Use injected clocks, provider/plugin/clipboard fakes, deterministic payloads, isolated temporary roots/databases, and failure injection. Tests must not access the owner's real clipboard, social accounts, health records, credentials, or public channels.
- Verify negative paths and state transitions, not only happy paths. In particular, distinguish pre-dispatch failure from post-dispatch ambiguity and prove retry cannot duplicate a social effect.
- Run the repository's current relevant lint/type/static/test gates discovered during implementation; do not claim live integration, certification, or release from local mocked evidence.

## 🤖 CodeRabbit Integration

### Story Type Analysis

**Primary Type:** Architecture / Integration  
**Secondary Types:** Security, API, privacy-sensitive local data, external provider mutation  
**Complexity:** High — one requested brownfield story delivered as independently gated vertical slices

### Specialized Agent Assignment

**Primary Agents:**

- `@dev` — implementation and pre-commit review
- `@architect` — quality gate for authority-plane reuse, plugin isolation, fallback, privacy, and publication lifecycle

**Supporting Agents:**

- `@qa` — adversarial, failure-injection, regression, and evidence review
- `@github-devops` — pre-PR review only; deployment/public release is not authorized by this story

### Quality Gate Tasks

- [ ] Pre-Commit (`@dev`): validate code quality, tests, default-off behavior, secret handling, authority reuse, and story File List.
- [ ] Pre-PR (`@github-devops`): validate compatibility, supply-chain/provenance, packaging impact, and that no external publication/deployment occurred.
- [ ] Pre-Deployment (`@github-devops`): N/A until a separate production/release authorization exists; if later authorized, require configuration, rollback, connector, consent, and authenticated smoke evidence.

### Self-Healing Configuration (Story 6.3.3)

**Expected Self-Healing:**

- Primary Agent: `@dev` (light mode)
- Max Iterations: 2
- Timeout: 15 minutes
- Severity Filter: CRITICAL

**Predicted Behavior:**

- CRITICAL issues: auto-fix within bounded iterations, then stop and report if unresolved.
- HIGH issues: document only for `@dev`; `@qa` full-mode review may auto-fix HIGH issues under its separately authorized workflow.
- MEDIUM issues: ignored by `@dev`; `@qa` records as debt.
- LOW issues: ignored.

### CodeRabbit Focus Areas

**Primary Focus:**

- Plugin isolation, ambient-authority/secret leakage, authenticated IPC, capability allowlisting, termination, and fail-closed behavior.
- Exact consent/payload/target binding, idempotency, single dispatch, receipt integrity, unknown outcomes, reconciliation, and duplicate-publication prevention.

**Secondary Focus:**

- Clipboard off-state zero reads, personalization/workspace isolation, retention/export/delete, and health-data limitation language.
- Gemini Live fallback truthfulness, modality separation, cancellation, compatibility with flags off, and redacted observability.

## Out of Scope

- Copying, porting, translating, vendoring, or mechanically deriving Mark-LI CC BY-NC code.
- Autonomous or unattended social publishing; bypassing preview or explicit consent; unofficial connectors masquerading as official ones.
- New social networks, wearable/device connectors, nutrition databases, medical/fitness advice, emotion diagnosis, or outcome claims not named in the request.
- Replacing Onyx's mission engine, permission broker, credential store, audit/evidence authorities, or existing Gemini Live path.
- Production deployment, public release, provider certification, account creation, OAuth consent grant, or use of the owner's live social channels.
- UI-first completion. UI may project accepted CLI/runtime state only after the corresponding slice is proven.
- Any modification to the currently accepted Onyx layout, humanoid, colors, positions, typography, controls, Three.js visual, animation, voice behavior, or interaction layout.

## Dependencies and Blockers

- Existing Onyx workspace, permission, credential, audit, memory, mission, and action receipt/reconciliation contracts are dependencies and must be characterized before modification.
- Owner-controlled provider credentials/scopes and test accounts are external prerequisites only for live connector evidence, not for safe default-off implementation and contract testing.
- If an official connector is unavailable for a selected target platform, the social mutation remains unavailable unless a separately declared fallback is explicitly approved; caption preview remains available.
- Missing `accumulated-context.md` is documented, not silently reconstructed. If it is later supplied, the story must be coherence-reviewed without weakening or expanding these AC.

## PO Validation Record — 2026-08-23

**Verdict:** GO — Ready for Development.

- `[AUTO-DECISION] Is a separate epic artifact required to validate coherence? → No.` (reason: no matching epic or `accumulated-context.md` exists in this checkout; the owner request, this story's bounded eight-gap scope, and the cited current Onyx normative documents provide the available authority without inventing roadmap scope.)
- `[AUTO-DECISION] Can one large brownfield story remain executable? → Yes, conditionally.` (reason: the owner requested this bounded set as one story and the work is partitioned into independently gated CLI-first slices; no slice may claim another slice or UI projection complete.)
- `[AUTO-DECISION] Can provider publication be accepted from mocks? → No.` (reason: local contract tests can make the implementation reviewable, but provider mutation remains disabled/unavailable until designated-account access, exact consent, receipt, observation, and reconciliation evidence exist.)
- `[AUTO-DECISION] Does the existing commercial-rights attestation for inherited Onyx waive the Mark-LI clean-room boundary? → No.` (reason: `OPEN_SOURCE_AND_API_LICENSE_REVIEW.md` addresses inherited Mark-XXXVII rights and unresolved distribution gates; it does not authorize copying or deriving Mark-LI implementation.)
- PO and change checklists applied: scope is traceable to the owner request; CLI-first and single-authority-plane constraints are explicit; ACs include deterministic positive/negative evidence; security/privacy defaults fail closed; publication separates preview, consent, dispatch, receipt, observation, and reconciliation; clean-room evidence is independently reviewable; release/deployment and live account consent remain out of scope.
- Brownfield caveat: the checkout contains extensive unrelated changes. Development must preserve them and establish an exact implementation baseline/file inventory before editing; this validation changes only this story artifact.

## File List

- `docs/stories/ONYX-MARK-LI-BROWNFIELD-GAPS-V1.story.md`
- `docs/onyx/adrs/ADR-0063-governed-capability-expansion-v1.md`
- `docs/onyx/ONYX_CAPABILITY_EXPANSION_PROVENANCE_V1.md`
- `core/enhanced_live_audio_v1.py`
- `core/governance_nucleus_v1.py`
- `core/governed_capability_host_v1.py`
- `core/plugin_runtime_v1.py`
- `core/clipboard_intelligence_v1.py`
- `core/wellness_tracker_v1.py`
- `core/vision_repetition_counter_v1.py`
- `core/governed_personalization_v1.py`
- `core/social_publish_v1.py`
- `core/social_video_asset_v1.py`
- `core/capability_expansion_runtime_v1.py`
- `core/capability_expansion_service_v1.py`
- `core/permission_broker.py`
- `plugins/_template.py`
- `scripts/onyx_plugin_cli.py`
- `scripts/onyx_personal_tools_cli.py`
- `scripts/onyx_personalization_cli.py`
- `scripts/onyx_social_cli.py`
- `scripts/onyx_vision_repetition_cli.py`
- `tests/test_enhanced_live_audio_v1.py`
- `tests/test_governed_capability_host_v1.py`
- `tests/test_plugin_runtime_v1.py`
- `tests/test_clipboard_intelligence_v1.py`
- `tests/test_wellness_tracker_v1.py`
- `tests/test_vision_repetition_counter_v1.py`
- `tests/test_governed_personalization_v1.py`
- `tests/test_social_publish_v1.py`
- `tests/test_social_video_asset_v1.py`
- `tests/test_capability_expansion_runtime_v1.py`
- `tests/test_capability_expansion_service_v1.py`
- `tests/test_capability_expansion_layout_freeze_v1.py`
- `tests/test_regressions.py`
- `main.py`

This list is the reconciled scoped implementation inventory. The working tree also contains unrelated pre-existing owner changes that are not claimed by this story.

## Change Log

| Date | Version | Description | Author |
|---|---:|---|---|
| 2026-08-23 | 0.1 | Initial brownfield draft from the owner request and prior Mark-LI audit boundary; added independently gated slices and governance constraints. | Chronos (`@sm`) |
| 2026-08-23 | 0.2 | PO validation: made clean-room evidence objectively verifiable, corrected the ADR lifecycle gate, documented autonomous decisions and brownfield caveat, and marked Ready for Development. | Themis (`@po`) |
| 2026-08-23 | 0.2 | CLI-first foundations implemented; 67 focused tests passed. | Dex (`@dev`) |
| 2026-08-23 | 0.3 | Wider live/regression gate fixed one headless UI regression and passed 203 tests plus 230 subtests; QA retained FAIL for four P1 boundaries. | Zeus (`@aexos-master`) |
| 2026-08-23 | 0.4 | Closed the four P1 implementation boundaries: native-sandbox attestation prerequisite, durable social ledger/reconciliation, runtime audio fallback, canonical permission/audit/kill authority composition, and non-durable raw clipboard handling. | Dex (`@dev`) |
| 2026-08-23 | 0.5 | Reconciled provenance, ADR, story checklist, implementation inventory, and current QA evidence; scoped combined gate passed 237 tests plus 230 subtests. | Zeus (`@aexos-master`) |
| 2026-08-23 | 0.6 | Added Slice 2 governed capability-host foundation and adversarial lifecycle, binding, audit, revoke, restart, and kill tests without runtime integration. | Vulcan (`@dev`) |
| 2026-09-01 | 0.7 | Reconciled the current public reference snapshot and reopened the existing exercise/social ACs for camera-signal repetition drafts and exact local-video asset leases; no reference implementation source is used. | Chronos (`@sm`) |
| 2026-09-01 | 0.8 | Added original CLI-first repetition estimation and ephemeral digest-bound social video leases; scoped QA is green while live camera composition and official provider activation remain open. | Vulcan (`@dev`) |
| 2026-09-01 | 0.9 | Recorded the owner's non-negotiable layout freeze and bound capability expansion to the immutable V40 HUD acceptance without modifying visual/runtime UI artifacts. | Zeus (`@aexos-master`) |
| 2026-09-01 | 1.0 | Composed the repetition counter with the existing normalized camera-attention observation through the governed wellness service; frames and identity data remain excluded and estimates persist only as owner-confirmable drafts. | Vulcan (`@dev`) |
| 2026-09-01 | 1.1 | Completed the canonical relevant regression/security gate and moved the local implementation to Ready for Review; provider activation, installation, and release remain unclaimed. | Zeus (`@aexos-master`) |

## Dev Agent Record

### Agent Model Used

Codex, GPT-5 family, orchestrated through Zeus (`@aexos-master`) with delegated architecture, development, adversarial QA, and provenance review.

### Debug Log References

- Focused implementation and adversarial tests: `98 passed` in the final independent QA code review.
- Combined scoped gate: `237 passed, 230 subtests passed in 20.13s` using an isolated Windows `--basetemp`.
- Targeted Ruff and `py_compile`: PASS.
- Slice 2 governed capability host: `111 passed` across the new host and adjacent nucleus tests; targeted Ruff and `py_compile` passed with temp/cache outside the candidate.
- Canonical pytest collection with repository `conftest.py`: BLOCKED before collection by pre-existing evidence drift, `current successor drifted: tests/test_onyx_live_activation_v19.py`.
- 2026-09-01 current-reference additions: targeted Ruff and `py_compile` PASS; isolated unit/regression selection `56 passed`; immutable canonical focused/security gate with repository `conftest.py` enabled `243 passed in 190.46s`.
- 2026-09-01 owner layout freeze: visual/runtime V40 presentation inputs unchanged; focused Ruff and `py_compile` PASS; capability plus layout-freeze selection `140 passed in 7.86s` with isolated Windows `--basetemp`. The older byte-exact V40 verifier observes a pre-existing three-line CRLF/LF-only difference between source and accepted packaged `ui.py`; normalized source content is identical and no visual file was rewritten.
- 2026-09-01 normalized camera/repetition composition: focused Ruff and `py_compile` PASS; focused camera/wellness/runtime/layout selection `39 passed`; full capability-expansion selection `143 passed in 7.07s`. No `ui.py`, QML, Three.js, image, voice, or animation artifact changed.
- 2026-09-01 canonical relevant gate with repository `conftest.py`: `143 passed in 155.40s`; layout-freeze regression included and PASS.
- NPM quality gates: not applicable because this Python checkout has no `package.json`.

### Completion Notes List

- The implementation is clean-room and uses Python standard-library components; no Mark-LI code, fixtures, prompts, packages, or artifacts were imported.
- Capability expansion is default-off and routes model requests through `CapabilityExpansionServiceV1` → `CapabilityExpansionRuntimeV1` → the existing permission broker → bounded capability modules.
- `GovernedCapabilityHostV1` is a connector-neutral foundation only: its registry is closed at construction and `GovernanceNucleusV1` remains the sole live authorization, audit, session, and durable kill authority.
- Plugin execution fails closed unless an injected native-sandbox provider returns a fresh HMAC-authenticated attestation bound to the exact launch contract. This repository does not claim to provide the production OS sandbox itself.
- Social publishing uses a durable SQLite request/consent/dispatch/receipt/reconciliation ledger and remains unavailable without an official authorized provider adapter and test account.
- Clipboard raw content is held only in a bounded process-memory TTL cache; durable state contains consent and content-free digest/metadata only.
- No live provider account was mutated, no publication was made, and no release/build/install claim is made by this story.
- The camera-free repetition estimator is a bounded draft-producing source/CLI candidate. It is not composed into the sealed HUD camera stream and has no physical-camera acceptance.
- The social video broker binds exact content signature, digest, size, MIME, scope and expiry without persisting a raw path. It supplies no official provider adapter and cannot publish by itself.

### Implementation File List

Reconciled with the scoped File List above and the provenance ledger in `docs/onyx/ONYX_CAPABILITY_EXPANSION_PROVENANCE_V1.md`.

## QA Results — Historical First Review (Superseded)

### Review Date: 2026-08-23

### Reviewed By: Argus (Test Architect)

### Reviewed Revision

Working-tree scope digest `4f69c34764ee324b298364cd8235002c6de633295b012df86a09c839f295877c` over the requested implementation files, tests, `main.py`, and ADR-0063. Repository baseline: `355504cb`.

### Gate Status

**Gate: FAIL**

The focused unit suite is green in isolation (`67 passed`), and targeted Ruff plus `py_compile` are green. The canonical focused pytest invocation cannot collect because the repository evidence gate reports `current successor drifted: tests/test_onyx_live_activation_v19.py`. More importantly, adversarial execution demonstrates missing mandatory AC behavior.

### Findings

- **P1 — Plugin process separation is not capability isolation (AC 3, 12).** `PluginHostV1` starts an ordinary Python child with a sanitized environment, but supplies no filesystem or network sandbox and no broker enforcement. A QA plugin successfully read `../outside-secret.txt` and returned `TOP_SECRET`. The response returned by `execute()` also includes the per-execution IPC `auth` token. This contradicts the required denial of direct filesystem/network access and secret exposure. ADR-0063 truthfully calls this “process isolation, not a native sandbox,” so the implementation cannot claim AC 3 complete.
- **P1 — Social single-dispatch and reconciliation are not durable (AC 11-14).** `SocialPublicationV1` stores requests, consent, dispatch-attempt state, receipts, and reconciliation state only in `_records`/`_active` memory. A QA restart simulation created the same normalized request twice and produced two provider dispatches (`actual=2`, durable expectation `=1`). After a real crash/restart, uncertain effects and receipts are lost, `publish-status`/`publish-reconcile` cannot recover them, and blind republication is possible.
- **P1 — Enhanced-audio runtime fallback is not wired (AC 2, 13-14).** `main.py` applies enhanced provider fields before each connection, but provider connection/session failures enter the generic reconnect loop and rebuild the same enhanced configuration. No production call passes `failure`/`fallback_attempted` to `resolve_status()`. Therefore pre-session failure, mid-session failure, cancellation, and fallback-loop prevention are only pure-function simulations, not host behavior.
- **P1 — Required story/repository gate evidence is incomplete (AC 4, 14-15).** Story status remains `Ready for Development`; every implementation task is unchecked; Dev Agent Record and implementation File List are empty; no per-file provenance ledger, dependency/license inventory, prohibited-source review, or packaged-source reconciliation was supplied. The canonical pytest gate is currently red before collection because of unrelated successor drift. Approval is prohibited while these conditions remain.
- **P2 — New capabilities do not consistently extend the existing authority/audit plane (AC 12-13).** Only enhanced audio is wired into `main.py`. Plugin, clipboard, wellness, personalization, and social modules use standalone JSON/SQLite/in-memory records and CLI-injected adapters; no reviewed wiring to the existing permission broker, action request/receipt store, audit health, kill/revoke lifecycle, or authoritative status projections was found.
- **P2 — Clipboard secret filtering is heuristic while accepted snapshots persist raw text (AC 5, 12).** Off-state zero-read behavior is correctly implemented, but accepted clipboard text is stored verbatim in SQLite and returned verbatim in previews. The small regex set cannot establish the story's broader restricted-data/no-secret guarantee, and no existing protected storage authority or at-rest control is integrated.

### Positive Evidence

- `pytest --noconftest` focused scope: `67 passed in 1.80s`.
- Targeted `ruff check`: passed.
- Targeted `py_compile`: passed.
- Clipboard off-state checks consent before invoking the reader; pause/revoke/scope/self-write paths are covered.
- Social in-process tests cover exact-consent drift, one dispatch per runtime, uncertain outcomes with receipts, and read-back verification.
- Wellness and governed-personalization focused contracts passed their supplied tests.
- ADR-0063 accurately limits local evidence and explicitly denies a native plugin-sandbox or live-provider claim.

### Required Before Re-review

1. Implement or explicitly descope AC 3: use an enforceable OS sandbox/broker boundary with filesystem/network/resource denial, do not return IPC authentication material, and add escape tests that verify denial.
2. Persist social ActionRequest/consent/dispatch-attempt/receipt/reconciliation state atomically in the canonical authority store; prove crash/restart recovery and duplicate prevention adversarially.
3. Wire enhanced-audio failure classification and one-time fallback into the live host for pre-session and mid-session failures, with truthful state/events.
4. Integrate each capability with the existing permission, audit-health, kill/revoke, workspace/principal, retention, and status authorities; add integration/failure-injection tests.
5. Complete AC 4 evidence, Dev Agent Record, implementation File List, task checklist, and move the story through the proper review lifecycle.
6. Repair the repository successor-evidence drift and rerun the canonical focused and relevant regression gates without bypassing `conftest`.

### Files Modified During Review

- Story file only: QA Results section. No application source or test code was modified.

[AUTO-DECISION] Should a green isolated unit suite override missing mandatory isolation, persistence, runtime fallback, and canonical regression evidence? → No (reason: the acceptance criteria require those behaviors and AEXOS forbids approval with missing AC implementations or a failing test gate).

[AUTO-DECISION] Should QA apply a lifecycle transition from `Ready for Development`? → No (reason: the canonical QA transition applies only from `InReview`; changing this story's lifecycle would exceed the authorized transition).

## QA Re-review — Current

### Review Date: 2026-08-23

### Gate Status

**Overall: CONCERNS — scoped code verdict PASS**

The four P1 code boundaries from the first review are closed. The final independent QA code review passed `98` focused tests plus targeted Ruff and `py_compile`; the broader scoped gate passed `237 tests plus 230 subtests`. The story is ready for review, but not Done or released, because the canonical repository gate still cannot collect while the unrelated V19 successor-evidence drift remains unresolved.

### Closed Findings

- Plugin launch is now impossible without an injected native sandbox's fresh command-bound authenticated attestation; IPC authentication material is not returned. A normal child process alone is explicitly insufficient and no production sandbox claim is made.
- Social request, consent, dispatch reservation, receipt, read-back, uncertain outcome, and reconciliation state are durable and atomically reserved across restart/process races.
- Enhanced-audio fallback is wired to classified pre-session enhanced-configuration rejection and attempts the existing audio mode once; unrelated, cancelled, and mid-session failures do not silently downgrade.
- Capability dispatch is composed through the existing permission/audit/kill boundary and fails closed on missing identity, scope, audit health, revocation, or unknown action.
- Clipboard raw content is non-durable and expires from process memory; durable records contain consent and content-free metadata/digests.

### Open Review/Release Boundaries

1. Repair or explicitly reconcile the pre-existing `tests/test_onyx_live_activation_v19.py` successor-evidence drift, then rerun the canonical suite with repository `conftest.py` enabled.
2. Supply and certify a real native OS sandbox adapter before enabling plugin execution outside tests.
3. Supply an official authorized social provider adapter, designated test account, and reversible live evidence before any publication capability can be called integrated or released.
4. Build/install/UI projections and public release remain outside the evidence produced by this story.

[AUTO-DECISION] Should scoped green code evidence be reported as a completed live integration or release? → No (reason: the canonical repository gate, production sandbox, provider credentials/adapters, designated-account proof, packaging, and release evidence remain separate gates).

## QA Incremental Review — 2026-09-01 Current Reference Reconciliation

### Gate Status

**Overall: CONCERNS — additive source/CLI code PASS; live integration incomplete**

The immutable canonical selection passed `243 tests in 190.46s`; targeted Ruff,
`py_compile`, and the final isolated selection (`56 passed`) also passed. QA
found and development closed two pre-verdict defects: renamed non-video content
is now rejected by binary signature, and sequence previews have a hard sample
bound. A product-name scan over the added/modified product code found no
reference-project or creator branding.

### Remaining Boundaries

1. The repetition estimator is not yet bound to the existing camera owner. That
   integration must ship as a new authenticated HUD/runtime successor, reuse the
   existing frame stream, retain no image/identity data, and pass physical
   calibration before the pending Slice 6 subtask can close.
2. The video asset lease is usable for exact local preview/consent binding, but
   no official social provider adapter, OAuth/account binding, designated test
   account, live dispatch receipt, read-back, or reconciliation proof exists.
3. The full repository regression/release/install gates were not run by this
   incremental review. The story therefore remains `In Progress` and no release
   or installed-runtime claim is authorized.
