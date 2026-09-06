# Story ONYX-BROWNFIELD-AUDIT-REMEDIATION-V1: Restore a Governed, Host-Wired Release Candidate

## Status

**In Progress** — AC 1 independently approved on isolated candidate `Onyx-Remediation-Clean-20260823-151210`; source checkout remains untouched.

## Executor Assignment

```yaml
executor: "@dev"
quality_gate: "@architect"
quality_gate_tools: ["pytest", "ruff", "release-verifiers", "provider-free-e2e"]
```

## Story

**As a** release owner of the brownfield Onyx desktop runtime,  
**I want** the audit findings remediated through ordered, CLI-first, independently verifiable slices,  
**so that** one authority plane controls host-wired capabilities and a truthful signed release candidate can be assessed without destroying concurrent work or overstating external readiness.

## Context and Evidence Basis

The authorized audit scope is the controlling requirement source for this remediation story. It confirmed these gaps: canonical pytest is blocked by retirement V19; the advanced-operations manifest has drifted; release closure has drifted from `packaging/onyx.spec`; global lint is not clean; authority is fragmented; Microsoft Graph, Google Workspace, Argos, plugins and social capabilities are not wired into the production host; kill/revoke behavior is fragmented; plugin timeout coverage is flaky; documentation/version surfaces have drifted; and the current release is unsigned.

`accumulated-context.md` was searched in `C:\MAAX_Assistant` and was not present at drafting time. Cross-story coherence was therefore established from the current checkout, existing Onyx stories, `docs/onyx/CURRENT_STATE_AUDIT.md`, `docs/onyx/PHASE11_LOCAL_PROJECT_AUDIT_LIVE_V1.md`, acceptance manifests, retirement checkpoints and connector-specific stories. If `accumulated-context.md` appears before implementation, the executor must review it and record any conflict before changing source.

### [AUTO-DECISION] Story identity and sequencing

- `[AUTO-DECISION] Which epic/story number applies? -> Use a named brownfield remediation story rather than inventing an epic sequence (reason: the repo uses named Onyx stories and no governing epic with exact AC wording was identified).`
- `[AUTO-DECISION] Can remediation start in the dirty checkout? -> No; first create an isolated, content-addressed candidate containing only explicitly claimed files (reason: the checkout is extremely dirty and concurrently modified).`
- `[AUTO-DECISION] Does authorization to correct all audit findings include build, signing, push or release? -> No; source remediation and local verification only, with signing/release retained as external gates (reason: the user explicitly prohibited push/release and the certificate is external).`

## Scope

### In scope

- Repair the canonical local quality gates and their deterministic evidence.
- Converge runtime authority, capability registration, kill and credential revocation behind one production host composition root.
- Wire the already-existing Graph, GWS, Argos, plugin and social modules into that host through CLI-first contracts.
- Reconcile packaging inputs, runtime closure, version/docs and provider-free end-to-end verification.
- Produce unsigned local candidate evidence that truthfully reports signing and release as blocked.

### Out of scope / external limits

- No reset, checkout-discard, delete, stash, clean, broad formatter, commit, push, PR, deployment, publication or release.
- No overwrite of a path whose exact candidate bytes have not been claimed and independently reviewed.
- No live provider call, OAuth consent, tenant/admin approval, social publication, production secret use or account mutation without separate authority.
- No certificate purchase/import, code signing, notarization, timestamping or reputation claim. `unsigned` remains a truthful terminal status until an authorized signer and certificate are available.
- No claim that source tests prove an installed/frozen runtime, that provider-free E2E proves a provider integration, or that a local candidate is released.
- No new product capability beyond connecting and governing modules already present in the audited scope.

## Acceptance Criteria

1. **Candidate ownership gate:** before source edits, an isolated worktree/copy or equivalent content-addressed candidate inventory records every intended path and digest; concurrent checkout bytes remain untouched. Any digest drift fails closed and requires renewed ownership.
2. **Canonical pytest restored:** the repository-defined canonical pytest command completes collection and execution without the retirement V19 blocker; the fix preserves historical retirement evidence and adds a regression proving the active successor reference cannot regress to a retired generation.
3. **Advanced-ops manifest reconciled:** the authoritative advanced-operations verifier and current manifest agree on exact selected files, digests, counts and successor/retirement semantics; stale V19/V20/V21 evidence is retained or retired only through the existing append-only protocol, never rewritten to force green.
4. **Release closure/spec parity:** one deterministic command compares `scripts/verify_release_runtime_closure_v1.py`, package staging and every Analysis/COLLECT input in `packaging/onyx.spec`; missing, duplicate, unmanifested or development-only inputs fail with stable machine-readable diagnostics.
5. **Global lint restored:** the documented global lint command exits zero on the owned candidate, with no repo-wide auto-fix over unowned files; lint exclusions are narrow, justified and covered by a test that rejects silent scope reduction.
6. **Single authority plane:** one production composition root is the sole issuer/validator for principal, workspace, capability, session, consent, approval, credential alias and revocation state. Connectors cannot mint parallel authority or bypass deny/default-off decisions.
7. **Unified kill/revoke:** a single idempotent CLI operation can revoke a session/capability/credential alias and terminate owned work; it is bounded, race-safe and durable, denies subsequent work before dispatch, never kills unrelated processes, and emits a redacted receipt.
8. **Microsoft Graph host wiring:** the production host exposes the existing Graph read/mail/calendar/drive/tasks paths only through registered capabilities, least-privilege scopes and authority checks. Default-off/provider-free tests prove no network, browser or token activity before explicit authorization.
9. **Google Workspace host wiring:** the existing GWS host/connector/live activation is reachable from the same composition root without provisioning at normal startup; account/workspace binding, vault aliases, scope checks, paging and revocation remain enforced.
10. **Argos host wiring:** Argos is registered as a governed capability with bounded inputs/outputs and receipts; it cannot become a second router, authority source or unbounded background service.
11. **Plugin host wiring and timeout determinism:** plugins run only through the governed host with allowlisted capability grants, bounded resources and fail-closed cancellation. Timeout tests use deterministic synchronization/fake clock or equivalent and pass repeatedly without wall-clock race dependence.
12. **Social host wiring:** social draft/preview/publish paths are registered under the common authority plane; publish remains default-deny and requires explicit per-action approval. Provider-free E2E proves no external post is made.
13. **CLI-first observability:** one CLI surface can list capability readiness and exercise provider-free flows for Graph, GWS, Argos, plugins and social. Output is schema-versioned, deterministic, bounded and redacts secrets, PII, content and raw local paths.
14. **Cross-connector denial invariants:** tests prove wrong principal/workspace, stale grant, revoked alias, missing consent, missing capability and cross-connector token reuse all fail before provider/network dispatch and leave auditable redacted denial receipts.
15. **Source and frozen E2E:** a provider-free source E2E and an isolated packaged-candidate E2E traverse CLI -> production host -> authority -> connector/plugin -> receipt -> kill/revoke. The packaged test is bound to the exact candidate digest and cannot pass by importing checkout source.
16. **Version/docs truth:** `core/version.py`, package metadata/spec, CLI `--version`, release docs and current-state docs report one version and distinguish implemented, host-wired, tested, packaged, signed and released states. Historical evidence is not silently edited.
17. **Release gate:** local packaging may occur only after AC 1-16 pass on the exact candidate. The closure report, hashes, SBOM/dependency inventory, malware-scan status, rollback instructions and unsigned status are recorded; signing and release remain blocked external gates.
18. **Regression and evidence quality:** focused tests, canonical pytest, global lint, closure/spec parity and provider-free E2E all exit zero from clean isolated invocations using a repository-local `--basetemp`; evidence contains exact commands, exit codes and candidate digest and contains no secret/PII/content leakage.

## Ordered Tasks / Executable Slices

### Slice 0 — P0 ownership and baseline gates (AC: 1, 18)

- [x] Capture a read-only inventory of intended source, test, packaging and documentation paths with SHA-256 digests.
- [x] Create an isolated candidate without copying transient pytest/runtime/build output; independently validate inventory and candidate root.
- [x] Record baseline command results without editing the concurrent checkout.
- [x] Stop on any ownership collision or digest drift; do not merge concurrent bytes heuristically.

### Slice 1 — P0 canonical quality and evidence gates (AC: 2-5, 18)

- [ ] Reproduce and repair the retirement V19 collection/execution blocker with a focused regression.
- [ ] Reconcile the advanced-ops selection/manifest through its append-only successor protocol.
- [ ] Make runtime-closure, staging and `onyx.spec` parity one deterministic fail-closed gate.
- [ ] Resolve global lint in owned files and prove lint scope cannot silently shrink.
- [ ] Run focused tests, then canonical pytest and global lint in separate fresh processes.

### Slice 2 — P1 authority, dispatch, kill and revoke (AC: 6, 7, 14)

- [ ] Name and document the production composition root and authority owner.
- [ ] Adapt existing grants/consent/approval/vault/session contracts behind that root; remove bypassing composition paths without deleting historical modules.
- [ ] Route dispatch through pre-dispatch authorization and post-action receipt validation.
- [ ] Consolidate kill/revoke into one idempotent operation with bounded process ownership and durable denial.
- [ ] Add adversarial tests for TOCTOU, stale grants, cross-workspace access, revoke-during-dispatch and unrelated-process safety.

### Slice 3 — Connector host wiring (AC: 8-12, 14)

- [x] Replace the plugin crash/timeout wall-clock race with deterministic timeout classification; retain one real-process smoke with reliable margin and explicit child termination, reap, and pipe-cleanup assertions.
- [x] Register Microsoft Graph capabilities and adapters in the production host; preserve least privilege and default-off startup.
- [x] Register Google Workspace using its existing host/connector and native-vault boundaries; normal startup must not provision.
- [x] Register Argos as a subordinate bounded capability.
- [x] Register plugin execution with grants, timeout/cancellation and redacted receipts; replace wall-clock flaky assertions with deterministic coordination and repeated-run coverage.
- [x] Register social draft/preview/publish; keep publish deny-by-default and approval-bound.
- [x] Prove every connector is unreachable through ungoverned direct dispatch from the production host.

### Slice 4 — CLI and provider-free E2E (AC: 13-15, 18)

- [x] Add/extend one CLI capability/readiness command backed by the production composition root.
- [x] Create a provider-free matrix for allow, deny, revoke and timeout across all five integration families.
- [x] Fence network, DNS, socket, browser, subprocess and provider SDK boundaries before host construction.
- [ ] Verify deterministic JSON, receipt correlation, bounded output and deep exception redaction.
- [ ] Run the same contract against source and an isolated packaged candidate; reject checkout-import leakage.

### Slice 5 — Release closure and truthful handoff (AC: 4, 15-18)

- [x] Reconcile package hygiene, `packaging/onyx.spec`, hidden imports/data and runtime closure for host-wired modules only.
- [ ] Align version and current documentation with evidence-backed maturity states.
- [ ] Generate candidate-bound closure, hashes, dependency/SBOM, scan and rollback evidence.
- [ ] Mark candidate `unsigned / not released`; hand signing/release to `@devops` only after separate authorization and external certificate availability.

## Dev Notes

### Implementation guardrails

- CLI First -> Observability Second -> UI Third. No UI slice is required by this story.
- Reuse current modules; do not globally rename or create a second authority/control plane.
- Every external effect must have authorization before dispatch and a validated receipt after completion.
- Default-off equivalence must be demonstrated, not inferred from flags.
- Preserve append-only evidence and distinguish current authoritative evidence from historical artifacts.
- Treat test/build directories, runtime databases, caches and generated evidence as untrusted inputs unless explicitly selected by a manifest.
- The repository has one root commit (`355504cb`) and a very large dirty/untracked surface; Git history is insufficient to establish ownership of current bytes.

### Relevant source surfaces (expected, not pre-authorized)

- Authority/host: production bootstrap/composition modules under `core/` and `scripts/bootstrap_onyx*.pyw`; exact owner path must be recorded in Slice 0.
- Graph: `core/phase8_microsoft_graph_*_v1.py`, `core/phase8_microsoft_graph_device_bootstrap_v2.py` and matching scripts/tests.
- GWS: `core/google_workspace_{host,connector,live}_v1.py`, `core/onyx_live_activation_google_workspace_v1.py` and matching scripts/tests.
- Argos/plugins/social: `core/argos_v1.py`, `core/plugin_runtime_v1.py`, `core/social_publish_v1.py`, their CLIs and tests.
- Kill/revoke: `core/posix_kill_signal_v1.py` plus the authority/session/vault modules discovered by the candidate inventory.
- Packaging/release: `scripts/package_hygiene.py`, `scripts/verify_release_runtime_closure_v1.py`, `packaging/onyx.spec`, `core/version.py` and version/release tests/docs.
- Advanced ops/retirement: `docs/onyx/acceptance/VE-ADVANCED-OPS-*.manifest.json`, `docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_*.json`, their verifiers and tests.

### Testing

- Use existing pytest style and a unique repository-local `--basetemp`; never rely on the Windows global pytest temp root.
- Avoid sleep-based timing assertions. Plugin timeout/cancel tests need barriers, events, injectable clocks or deterministic fake workers and a repeated-run test.
- Use subprocess isolation for bootstrap, frozen mode, environment and import-closure checks.
- Install provider/network fences before constructing the host. A late monkeypatch is not evidence of default-off behavior.
- Test nested exception `__cause__`/`__context__`, stdout/stderr and receipts for secret, token, PII, payload and raw-path leakage.
- Required final sequence: focused slice tests -> canonical pytest -> global lint -> closure/spec parity -> provider-free source E2E -> isolated packaged E2E. Each step must be separately attributable to the exact candidate digest.

## 🤖 CodeRabbit Integration

### Story Type Analysis

**Primary Type:** Architecture/Security remediation  
**Secondary Types:** Integration, Deployment/Packaging, CLI/API  
**Complexity:** Critical — cross-cutting authority, external connectors and release evidence.

### Specialized Agent Assignment

- **Primary:** `@dev` for implementation and pre-commit review.
- **Quality gate:** `@architect` for single-authority and source/frozen trust boundaries.
- **Supporting:** `@qa` for adversarial/repeatability review; `@devops` only for separately authorized packaging/signing/release gates.

### Quality Gate Tasks

- [ ] Pre-Commit (`@dev`): candidate-bound focused/canonical tests, lint, redaction and diff review.
- [ ] Pre-PR (`@devops`): not authorized in this story; report-only until explicit push/PR authority.
- [ ] Pre-Deployment (`@devops`): blocked; requires signed candidate, rollback evidence and separate release authority.

### Self-Healing Configuration

- Primary Agent: `@dev` (light mode)
- Max Iterations: 2
- Timeout: 15 minutes
- Severity Filter: CRITICAL only
- CRITICAL: repair only within owned candidate paths and rerun affected gates.
- HIGH: document and return to Architecture/QA; do not widen authority.

### CodeRabbit Focus Areas

- Parallel authority, direct connector bypass, stale/revoked grant TOCTOU and cross-workspace leakage.
- Kill scope, idempotency, cancellation races and unrelated-process safety.
- Flaky wall-clock tests and fail-open timeout behavior.
- Package/spec/closure drift, checkout imports and unmanifested inputs.
- Secret/PII/content/path leakage and false signed/released/provider-tested claims.

## Story Draft Checklist Validation

| Category | Status | Notes |
|---|---|---|
| Goal and context clarity | PASS | Audit findings, value, order and non-goals are explicit. |
| Technical implementation guidance | PASS | Five executable slices, expected surfaces and authority invariants are defined. |
| Reference effectiveness | PASS | Current Onyx audit, manifests, checkpoints and connector stories are named; missing accumulated context is disclosed. |
| Self-containment | PASS | A developer can begin after Slice 0 ownership succeeds without inventing product requirements. |
| Testing guidance | PASS | Canonical, focused, deterministic timeout, denial, source/frozen and release gates are specified. |
| CodeRabbit integration | PASS | Agents, gates, self-healing and focus areas are complete. |

**Final assessment:** **READY AS A DRAFT; BLOCKED FOR IMPLEMENTATION ENTRY** until AC 1 establishes an isolated, content-addressed and independently reviewed candidate. External signing and release remain blocked after local implementation.

## Change Log

| Date | Version | Description | Author |
|---|---:|---|---|
| 2026-08-23 | 0.1.0 | Initial brownfield remediation story from authorized audit findings | Chronos (`@sm`) |
| 2026-09-01 | 0.2.0 | Recorded frozen Founder/Document Intake isolation repairs, canonical package qualification, installed lifecycle failure evidence, and bounded refusal-diagnostic repair | Vulcan (`@dev`) |

## Dev Agent Record

### Agent Model Used

Codex GPT-5 family, orchestrated by Zeus (`@aexos-master`).

### Debug Log References

- AC 1 candidate: `C:\MAAX_Assistant\Onyx-Remediation-Clean-20260823-151210`
- Inventory: 2,993 files.
- Root digest (`relpath\0sha256\n`): `a12927131ce9965357bbf1e8a091c1125eeffa21268c2fbdfeb83caf91fc46e6`.
- Independent QA: APPROVED; no caches, VCS metadata, build/runtime output, links or content drift.
- Plugin timeout flakiness subtask: `tests/test_plugin_runtime_v1.py` passed `21` focused tests; deterministic timeout classification passed `50/50` repeated isolated runs; real timeout smoke passed with child termination/reap and stdin/stdout/stderr closure assertions; focused Ruff and `py_compile` passed. Canonical collection remains blocked outside this ownership by the pre-existing V19 successor-evidence drift.
- Governed Graph/GWS ports: focused Ruff and `py_compile` passed; provider-free port/host plus existing Graph/GWS regression passed `256`, with `1` pre-existing skip. No credentials or network were used.
- Slice 3/4 host composition: IDS decisions were CREATE `core/capability_composition_v1.py`, CREATE `scripts/onyx_capabilities_cli.py`, and ADAPT only the initialization/cleanup seams in `main.py`; existing six capability-port modules and the plan-only router were reused unchanged.
- Focused composition/CLI/port gates passed `40`; Ruff and `py_compile` passed. An expanded V16-V19 regression run passed `86` and failed `8` only because this clean snapshot intentionally has no `.venv/Scripts/python[w].exe`; no source failure from the owned slice was observed. The 50k suite and packaged-candidate E2E were not run in this subtask.
- Packaging closure IDS: ADAPT the seven assigned packaging/runtime seams; CREATE one focused closure/smoke test module; CREATE the additive V54 generator/verifier/fixture/test/receipt set because V53 uses that complete append-only authority convention.
- Packaging closure verification: focused closure/V54/composition/CLI `19 passed`; focused Ruff and `py_compile` passed; standalone closure V2 and V54 verifiers passed. The 163 V1-V53 workflow authority files matched `C:\MAAX_Assistant\Onyx` by SHA-256 with zero missing and zero drift. The candidate has no `package.json`, so npm lint/typecheck scripts are unavailable.
- Provider-free A15 + A9.1-A9.3 adapter IDS: CREATE `core/capability_ports/guild_v1.py` and `budget_v1.py` because no capability-port equivalents existed; ADAPT only the closed composition registry, capability CLI policy-only projection, current CLI test, and new focused tests; REUSE exact accepted Guild snapshot types, `HostBoundCapabilityPortV1`, and the governed host kill latch. Historical guild modules/manifests and A9.4/A9.5 execution remain untouched.
- Provider-free Guild/budget adapter verification: focused composition/CLI/adapters passed `30`; focused Ruff and `py_compile` passed. Self-critique considered atomic-save failure, replay races, malformed persisted state, quota boundaries, uncertain outcomes, duplicate stages, and hostile escalation text; locking, transactional rollback, strict schemas, fail-closed restoration, exact-prefix validation, and content-free host receipts cover those cases. No network, browser, subprocess, build, release, Git, or original-checkout operation was performed; no `package.json` exists for npm lint/typecheck.
- Frozen Founder V17 and Document Intake V18.1 initially failed because their smoke-only control-plane redirects did not cover both the `core.paths` reference and the direct import held by `core.control_plane`. Both now redirect immediately before live-host instantiation and restore both references in `finally`; delaying the V18 redirect preserves the real V7 authority state. Focused isolation regressions, source diagnostics, and both frozen smokes passed.
- The canonical `1.1.10` bundle completed every configured provider-free/frozen gate and produced Setup plus Portable artifacts. Portable extraction/startup and isolated Setup install/startup/uninstall passed. Production Setup SHA-256 before installation was `733E5613AC2A7DEF0E9573E4DC4C76A3E80D1FD59FABFF769229FBE26CFC6200`; the installed `Onyx.exe` matched the qualified bundle byte-for-byte.
- Installed lifecycle validation did not pass: the authenticated client returned `EXIT_REFUSED` (`20`) and the resident remained alive. No forced termination was used. The protocol discarded the resident's exact refusal cause when `begin_shutdown` returned false; the source now preserves a bounded `shutdown_status()` refusal detail in the authenticated receipt. The repair passed `15` lifecycle tests plus focused Ruff/format.
- A rebuild containing the refusal-diagnostic repair regenerated Setup (`ACC187FA0C60B9E1C21ED9C11CE80623FA50B30DF67F257E71D8E8EBD29650A3`) and Portable (`20E1A5E59D5A6D071761866D1E14160119817456B5933EEAC79CBFE200869A71`) and repeated the configured frozen smokes. Final isolated Setup qualification was intentionally not claimed: its log refused to proceed because production PID `25368` remained resident without a usable maintenance record. Only the temporary smoke Setup processes were stopped; the production Onyx process was not terminated.
- Independent focused QA passed `72` tests across Founder/Document Intake isolation, lifecycle/PortAudio hardening, installer lifecycle, Capability Nexus current, and social publication/capability ports. The current Nexus verifier passed with 32 historical catalogs and 67 current inputs; direct social CLI help passed. This does not convert the failed installed shutdown into a pass.

### Completion Notes List

- Slice 0 completed without changing the source checkout. No Git mutation, build, signing or release was performed.
- Plugin timeout classification no longer depends on a `0.1s` wall-clock race. Native sandbox attestation and fail-closed dispatch remain unchanged; the sandbox adapter contract now explicitly owns timeout termination, reap, and IPC pipe cleanup before raising `TimeoutExpired`.
- Graph and Google Workspace now expose closed, default-off capability ports below `GovernedCapabilityHostV1`; concrete factories remain lazy/injected, status and construction remain provider-free, local host revoke is distinct from explicit provider disconnect, and receipts expose only bounded digests/counts.
- The production `OnyxLive` constructor now composes a closed provider-free capability host immediately after Governance V16 initialization and before later activation/provider seams. Default status/list construct no concrete connector, while explicitly injected factories are canonicalized behind host authorization.
- The versioned JSON CLI exposes `status`, `list`, and `safe-test` without raw paths/content. Router output is plan/attestation only; dispatch, binding revoke, and idempotent global kill remain single-host operations.
- Package staging now includes the exact closed capability runtime set and excludes the general test tree. Only three hash-bound historical source receipts required by the immutable activation chain are staged as data; pytest and every undeclared test remain excluded. PyInstaller uses explicit capability hidden imports, and the release driver invokes the real frozen `--capabilities-smoke-v1` executable from an isolated external working directory with an allowlisted environment and fail-closed origin/port/dispatch checks.
- Release Workflow V54 additively binds the packaging-closure release paths while preserving V1-V53 byte-for-byte. No package was built; signing and release remain unproven and unauthorized.
- Guild profiles, handoffs, and workflows now enter the production capability registry only as principal/workspace-bound read-only projections and replay-protected policy validation. Budget reservations are provider-free, atomic under one ledger lock, hard-capped, idempotent, restart-serializable through an injected store, and retain uncertain outcomes as consumed capacity. Neither adapter grants permission or exposes publish/deploy/spend/direct-dispatch; governed kill denies later work.
- Capability Nexus current authority was rebound to the corrected permission broker while preserving all 32 historical manifests as immutable evidence. The standalone verifier passes with 67 current inputs.
- The social CLI now bootstraps its project root when executed directly, so `python scripts/onyx_social_cli.py --help` succeeds independently of checkout `PYTHONPATH` state.
- PortAudio capture and playback now use callback/stream-owner abort-close lifecycle seams. Focused concurrency tests and a real native-device start/I/O/abort/close probe pass; this does not activate any social or workspace provider.
- Installer lifecycle refusal receipts now retain the exact bounded runtime diagnosis when maintenance is refused before cleanup begins; authentication, identity matching, capability rotation and fail-closed behavior remain unchanged.
- Windows frozen Qt diagnosis proved that the host `PATH` caused PyInstaller to capture Poppler's unversioned ICU beside Qt. Build discovery is now sanitized, the collision is filtered and post-build validation rejects recurrence. The smoke then advanced through V11 and exposed a stale Orb-era visual assertion, now rebound to the current V14 humanoid contract.
- The rebuilt humanoid smoke and V24 preflight passed. Capability smoke then exposed a bootstrap protocol bug: clean `SystemExit(0)` was converted to diagnostic failure 70. Clean CLI exits now remain zero while non-zero diagnostic failures retain bounded conversion and traceback logging.
- After the exit fix, frozen capability execution returned the full closed 17-family registry, but the release gate still expected the original five-family slice. The gate now binds all current families and cross-checks that static package expectation against `CAPABILITY_OPERATIONS`; provider dispatch remains false and every family must fail closed in the provider-free smoke.

### File List

- `docs/stories/ONYX-BROWNFIELD-AUDIT-REMEDIATION-V1.story.md` — new story; the only file owned/created by Chronos.
- `core/plugin_runtime_v1.py` — clarified fail-closed native-sandbox timeout cleanup contract for this subtask.
- `tests/test_plugin_runtime_v1.py` — deterministic timeout injection plus real-process termination/reap/pipe-cleanup smoke.
- `core/capability_ports/graph_v1.py` — governed lazy Microsoft Graph port with exact operation/effect/scope registry and redacted receipts.
- `core/capability_ports/google_workspace_v1.py` — governed lazy Google Workspace port over the existing live adapter actions.
- `tests/test_capability_port_graph_v1.py` — default-off, scope, provider-fence, operation-mismatch, redaction and lifecycle coverage.
- `tests/test_capability_port_google_workspace_v1.py` — provider-free status, exact actions/scopes, local revoke versus provider disconnect, redaction and adversarial fences.
- `docs/stories/ONYX-BROWNFIELD-AUDIT-REMEDIATION-V1.story.md` — plugin-timeout subtask checklist, validation evidence, completion note, and File List update.
- `core/capability_ports/argos_v1.py` — ADAPT: bounded local-state-only Argos reads, explicitly untrusted content and structurally non-actionable output.
- `core/capability_ports/plugin_v1.py` — ADAPT: separate plugin lifecycle and exact `execute.test.echo` route while preserving native-sandbox attestation in `PluginHostV1`.
- `core/capability_ports/social_v1.py` — ADAPT: preview/consent/dispatch/observe/reconcile transitions delegated to the existing durable publication ledger.
- `core/capability_ports/unified_router_v1.py` — CREATE: injected-host plan/attest-only router with no connector or capability dispatch method.
- `tests/test_argos_capability_port_v1.py` — governed local-read, untrusted-content, no-action and lifecycle distinction coverage.
- `tests/test_plugin_capability_port_v1.py` — lifecycle/execution separation, exact echo delegation and revoke/disconnect/close/kill distinction coverage.
- `tests/test_social_capability_port_v1.py` — durable preview/consent/dispatch/observe flow, blind-dispatch denial and lifecycle distinction coverage.
- `tests/test_unified_router_capability_port_v1.py` — exact `GovernedCapabilityHostV1` injection and plan/attest-without-dispatch coverage.
- `core/capability_composition_v1.py` — CREATE: production provider-free composition root, canonical operation aliases, closed host registry and single terminate surface.
- `scripts/onyx_capabilities_cli.py` — CREATE: schema-versioned deterministic `status`, `list` and provider-free `safe-test` JSON CLI.
- `tests/test_capability_composition_v1.py` — CREATE: source E2E, five-family allow/deny/revoke/timeout matrix, stale/cross-scope denials, lifecycle ordering and router/host boundary coverage.
- `tests/test_onyx_capabilities_cli.py` — CREATE: socket/DNS/browser/subprocess-fenced CLI construction and redacted deterministic JSON coverage.
- `main.py` — ADAPT: minimal post-governance composition plus partial-initialization and runtime-shutdown kill cleanup.
- `core/capability_ports/__init__.py` — ADAPT: closed capability-port package marker.
- `scripts/package_hygiene.py` — ADAPT: exact capability runtime membership and test-free staging.
- `packaging/onyx.spec` — ADAPT: test exclusion and explicit capability hidden imports.
- `scripts/build_release.py` — ADAPT: isolated, sanitized frozen capability smoke and exact-family refusal checks.
- `scripts/bootstrap_onyx.pyw` — ADAPT: frozen-only capability smoke route before normal activation.
- `scripts/onyx_capabilities_cli.py` — ADAPT: exact five-family safe-test membership and bounded module origins.
- `scripts/verify_release_runtime_closure_v2.py` — CREATE: fail-closed capability/spec/test closure verifier.
- `tests/test_release_runtime_closure_v2.py` — CREATE: focused membership, staging and frozen-smoke tests.
- `scripts/generate_release_workflow_v54.py` — CREATE: additive V54 transition generator.
- `scripts/verify_release_workflow_v54.py` — CREATE: V54 and immutable V53 boundary verifier.
- `tests/fixtures/release_workflow_transition_v54.json` — CREATE: V54 current-path SHA-256 fixture.
- `tests/test_release_workflow_transition_v54.py` — CREATE: V54 predecessor and closure regression.
- `docs/onyx/checkpoints/RELEASE_WORKFLOW_V54_VERIFIER_RECEIPT.json` — CREATE: V54 verifier/test hash receipt.
- `core/capability_ports/guild_v1.py` — CREATE: read-only A9.1-A9.3 projections and bounded replay/monotonic policy validators.
- `core/capability_ports/budget_v1.py` — CREATE: provider-free atomic hard-quota reservation ledger with injected restart persistence.
- `core/capability_composition_v1.py` — ADAPT: register closed `guild` and `budget` capability families.
- `scripts/onyx_capabilities_cli.py` — ADAPT: expose `guild`/`budget` membership as policy-only in provider-free safe-test output.
- `tests/test_guild_capability_port_v1.py` — CREATE: binding, escalation, malformed/replay/stale handoff, duplicate stage and kill coverage.
- `tests/test_budget_capability_port_v1.py` — CREATE: exhaustion, concurrency, retry, uncertain outcome, restart and kill coverage.
- `tests/test_onyx_capabilities_cli.py` — ADAPT: current family membership and policy-only CLI assertion.
- Remaining implementation file list — pending for the other remediation slices; Dev must reconcile exact candidate-owned paths before review.
- `scripts/onyx_social_cli.py` — ADAPT: direct-entry project-root bootstrap without changing provider behavior.
- `tests/test_social_publish_v1.py` — ADAPT: isolated direct CLI regression.
- `docs/onyx/acceptance/VE-CAPABILITY-NEXUS-CURRENT-V1-E6-001.manifest.json` — ADAPT: current-only permission-broker digest and root.
- `scripts/verify_capability_nexus_current_v1.py` — ADAPT: current-root receipt while historical evidence remains immutable.
- `main.py` — ADAPT: non-blocking callback playback and stream-owner capture/playback abort-close cleanup.
- `tests/test_runtime_shutdown_hardening_v1.py` — ADAPT: underflow, callback stop and exact stream-owner teardown regressions.
- `scripts/qt_bundle_probe_v1.py` — CREATE: minimal PySide6 frozen-runtime diagnostic.
- `tests/test_windows_qt_bundle_toolchain_v1.py` — CREATE: sanitized environment, collision denial and spec regression coverage.
- `core/onyx_live_activation_v17.py` — ADAPT: smoke-only dual-reference control-plane isolation with restoration.
- `core/onyx_live_activation_v18.py` — ADAPT: post-activation dual-reference control-plane isolation that preserves V7 authority state.
- `tests/test_founder_smoke_control_plane_isolation_v1.py` — CREATE: Founder smoke path/reference isolation regression.
- `tests/test_document_intake_smoke_control_plane_isolation_v1.py` — CREATE: Document Intake smoke timing/path/reference isolation regression.
- `core/installer_lifecycle_v1.py` — ADAPT: authenticated refusal receipts retain the exact bounded runtime status detail.
- `tests/test_installer_lifecycle_v1.py` — ADAPT: real named-pipe regression for exact refusal-detail propagation.

## QA Results

Pending independent validation of candidate ownership, all ACs, deterministic evidence and external-gate truthfulness.
