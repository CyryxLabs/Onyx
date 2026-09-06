# ONYX-GWS-1.2.0 - Source-only default-off Windows Google Workspace activation

## Status

**Done — Source-only Gate A Approved**

Independent Architecture, QA and Reliability reviews issued GO for the v1.2.6
source-only implementation and isolated source evidence against the exact
seven-file baseline whose aggregate SHA-256 is
`0502ad2243d1d4b8d23fd032ccd0c4cff0c58c9940c0c635cd10228e664fecce`.
The canonical enabled branch must verify that exact manifest and dependency
aggregate before importing any Google dependency or composing the service. Git
still reports the accepted 1.0/1.1 connector, host, CLI, tests and stories as
untracked. Gate B (Git/pre-PR provenance) and Gate C (build/install/provider/live/
release) therefore remain explicitly NO-GO until separately authorized and
proven; the Gate A verdict cannot be inherited by either later gate.

## Executor Assignment

```yaml
executor: "@dev"
quality_gate: "@architect"
quality_gate_tools:
  - provenance and source-boundary verification
  - activation, policy and lifecycle contract tests
  - activation composition and rollback fault tests
  - independent adversarial QA review
```

## Story

**As the** Onyx owner,  
**I want** the accepted Google Workspace service exposed through one
default-off, policy-governed tool contract on a dedicated Windows source
activation branch,  
**so that** Onyx can connect, disconnect and read Gmail/Calendar within my exact
owner scope without changing the current V24 source path, installed V31 product
or owner runtime during this source-only implementation.

## Scope and dependencies

This story succeeds `ONYX-GWS-1.1.0`, which is Done only for the isolated
Windows source/native-host boundary. It adds live composition around the 1.1
host; it does not replace or bypass the connector, native vault, OAuth loopback,
budgets, CAS, error taxonomy or cleanup guarantees already accepted there.

The approved Vega design for this story requires:

- one model-visible tool named exactly `google_workspace`;
- exact actions `status`, `connect`, `disconnect`, `list_gmail_messages` and
  `list_calendar_events`;
- owner-scoped autonomous read-only operations, while `connect` and
  `disconnect` remain consequential;
- exact dual opt-in flags
  `ONYX_GOOGLE_WORKSPACE_LIVE_V1=true` and
  `ONYX_GOOGLE_WORKSPACE_CONNECTOR_V1=true`;
- a dedicated activation/bootstrap/launcher branch over the exact V24 source;
- no modification of the current V24 activation/bootstrap/launcher files or the
  installed V31 product; and
- transactional source-composition rollback that unregisters only this branch's
  tool and closes only this branch's resources on partial startup.

## Split provenance gates

### Gate A — exact source-development baseline: approved

`@architect` independently recomputed all seven dependency sizes and SHA-256
values from the canonical working tree, applied the manifest's documented
path-sorted `path|size_bytes|sha256` plus LF canonicalization, and reproduced:

`0502ad2243d1d4b8d23fd032ccd0c4cff0c58c9940c0c635cd10228e664fecce`

This closes only the prerequisite for bounded source implementation. When the
canonical dual flags are present, the new source activation gate must validate
the manifest schema, exact seven-path set, sizes, per-file hashes and this fixed
aggregate before any Google connector/host/live module import. Missing, extra,
changed or ambiguous input fails closed with zero Google import, vault, listener,
browser, network or provider effect. When the flags are absent, exact V24
equivalence still requires no Google manifest or dependency path access.

### Gate B — Git/pre-PR provenance: blocked

The manifest truthfully classifies itself as an unauthenticated local untracked
byte snapshot. It proves byte equality at review time, but not author identity,
commit ancestry, approved source indexing or release provenance. Before PR,
`@devops` must be separately authorized to track the exact seven dependency
bytes and manifest together, then recompute the aggregate and rerun source and
provenance gates from that indexed baseline. This story does not authorize
staging, commit, push or PR.

### Gate C — build/install/provider/live/release: blocked

Git tracking alone cannot close candidate-bound package, real install/rollback,
provider, deployment or release gates. Those remain separately authorized and
must never inherit the source snapshot or source-test verdict.

Gate A accepts the exact source-development baseline only when:

1. each dependency is present in an approved source index or an independently
   authenticated provenance manifest tied to exact bytes;
2. exact SHA-256 values and repository-relative paths are recorded before the
   first 1.2 implementation edit;
3. no dependency is accepted merely because it exists in a mixed working tree;
4. the 1.1 Done/QA/architecture evidence is traceable to those exact bytes; and
5. `@architect` records GO for that exact baseline.

The accepted seven-file set is:

- `core/google_workspace_connector_v1.py`;
- `core/google_workspace_host_v1.py`;
- `scripts/onyx_google_workspace.py`;
- `tests/test_google_workspace_connector_v1.py`;
- `tests/test_google_workspace_host_v1.py`;
- `docs/stories/ONYX-GWS-1.0.0.md`; and
- `docs/stories/ONYX-GWS-1.1.0.md`.

## Acceptance Criteria

1. Source implementation is bound to manifest
   `docs/onyx/evidence/ONYX_GWS_1_0_1_1_SOURCE_PROVENANCE_20260810.json` and exact
   aggregate SHA-256
   `0502ad2243d1d4b8d23fd032ccd0c4cff0c58c9940c0c635cd10228e664fecce`.
   With the canonical dual flags present, a minimal pre-import verifier checks
   the manifest schema, exact seven repository-relative paths, sizes, individual
   SHA-256 values and fixed aggregate before any Google dependency import or
   runtime composition. Missing, changed, extra or ambiguous input fails closed.
   This closes only source-development provenance; the local untracked manifest
   is not Git provenance and cannot authorize PR, build, package, installation,
   provider access, deployment, live product activation or release.
2. The live branch exposes exactly one new model-visible declaration named
   `google_workspace`; no second declaration, per-action tool alias, legacy name
   or duplicate registry entry exists. The declaration has one exact `action`
   enum containing only `status`, `connect`, `disconnect`,
   `list_gmail_messages` and `list_calendar_events`; unknown, blank, differently
   cased or whitespace-padded actions are rejected before service/provider use.
3. `status`, `connect` and `disconnect` accept no action-specific model input.
   `list_gmail_messages` accepts only the connector's bounded Gmail query, with
   the existing `is:unread` default. `list_calendar_events` requires exact
   `time_min` and `time_max` values accepted by the existing RFC3339/window
   contract. Extra properties, model-supplied owner/account/provider identity,
   credentials, tokens, codes, PKCE material, budgets, policy decisions or
   approval claims are rejected.
4. Live selection recognizes only the complete canonical pair
   `ONYX_GOOGLE_WORKSPACE_LIVE_V1=true` plus
   `ONYX_GOOGLE_WORKSPACE_CONNECTOR_V1=true`. Both absent selects the exact V24
   path. Any one flag alone, alternative value, different casing, leading or
   trailing whitespace, duplicate/conflicting source or malformed environment
   fails closed before imports, paths, vaults, logs, listeners, tools, threads,
   browser, network or provider activity.
5. A new dedicated activation module authenticates and composes the exact V24
   activation as its predecessor. New dedicated bootstrap and launcher files
   select this branch only for the canonical flag pair. Existing
   `core/onyx_live_activation_v24.py`,
   `scripts/bootstrap_onyx_live_v24.pyw`,
   `scripts/launch_onyx_live_v24.pyw` and the installed V31 tree remain
   byte-for-byte unchanged by this story.
6. With both Google flags absent, source import, bootstrap preflight, launcher
   selection, tool enumeration, status inspection and shutdown produce zero
   Google side effects: no Google module/service factory construction, native
   vault access, metadata/seal/journal/lock/witness path access, directory/file
   creation, listener, browser, thread, audit row, provider/DNS/network request
   or change to the V24 declaration set.
7. With the canonical pair present, startup first authenticates the exact
   predecessor and provenance manifest, then creates one
   `GoogleWorkspaceHostServiceV1` through the accepted production factory and
   registers one tool adapter. The live controller owns this service for its
   full lifetime, rejects partial construction, and closes it during startup
   rollback, normal shutdown and exceptional shutdown without leaking listener,
   lease, pin, thread, socket or pending authorization state.
8. The host-owned policy boundary classifies `connect` and `disconnect` as
   consequential actions requiring an exact trusted decision bound to tool,
   action, owner, workspace, account binding, arguments, nonce/trace and expiry.
   Model text, autonomous mode and prior approval cannot approve either action.
   `status`, `list_gmail_messages` and `list_calendar_events` may execute without
   a per-request approval window only when the trusted owner-autonomy profile is
   active and the request is bound to the current owner/workspace/account with
   read-only Google scopes; otherwise they fail closed or use the existing
   trusted confirmation path. No global policy bypass is introduced.
9. The live adapter delegates only to the 1.1 host service and existing
   connector contracts. It never calls Google directly, creates a second OAuth
   flow, reads native-vault records itself, accepts a transport/model substitute
   in production, expands scopes, writes email/calendar data, sends messages,
   creates events or exposes the isolated CLI as a runtime subprocess.
10. Every attempted action emits one bounded, versioned and redacted event tied
    to the current trusted trace/request identity. Provider idempotency remains
    one separate logical reservation/result per binding and idempotency digest;
    a fresh approved execution appends a `fresh` trace event atomically with its
    logical result, and every approved replay appends an authenticated immutable
    `replay` trace event before returning the existing result. Replay-event
    audit failure fails closed and never redispatches the provider. Events bind
    action, argument digest, idempotency digest, trace, fresh/replay class and
    redacted logical-result references. Decision events and logical records
    contain only pseudonyms, bounded states/classes and digests; they never
    contain raw owner/account identity, Gmail query, message/event content,
    authorization URL/code/state, tokens, PKCE material, client configuration,
    native errors, paths or secrets.
11. `connect` and `disconnect` return only normalized redacted results derived
    from `GoogleProviderReceiptV1`. A conclusive provider/local postcondition is
    independently re-read through host `status`; the action is `succeeded` only
    when the expected connected/disconnected state and exact binding are
    observed. Failure after possible provider mutation remains
    `UnknownOutcome`, produces a reconciliation-required receipt and is never
    retried, relabelled as denied or hidden by cleanup/rollback errors.
12. `status` and both list actions return bounded typed projections only. Gmail
    and Calendar use the existing pagination, result, time, response and budget
    limits; response order and truncation are deterministic; raw provider
    payload, headers, tokens and unselected private fields never reach model,
    log or audit output. Read actions perform no provider write and do not change
    OAuth grant scopes.
13. Post-verification is mandatory for all actions: `status` verifies service,
    binding and anchor health; connect/disconnect verify the terminal grant
    state; reads verify the receipt/result digest, scope, account binding,
    provider-read classification, page/item limits and no-mutation condition.
    Missing, malformed or contradictory post-verification fails closed, with
    `UnknownOutcome` whenever an external attempt may have occurred.
14. Source activation composition is transactional within the process. Until
    predecessor authentication, manifest verification, policy binding, host
    service construction and exact tool registration all succeed, the new branch
    is not published as selected. Failure at any stage unregisters only the new
    declaration, closes only branch-owned resources and returns the exact V24
    predecessor object graph. Tests inject faults at every composition and
    cleanup boundary; they do not create or mutate an install root, package
    selector, shortcut, registry value or installed file.
15. Focused source tests cover exact tool declaration/schema, all five routing
    actions, trusted policy classification, owner/account/workspace isolation,
    audit redaction, receipts, post-verification, host lifecycle, startup and
    shutdown fault injection, concurrency, cleanup and `Denied` versus
    `UnknownOutcome`. Tests prove that provider methods are not reached on
    declaration, argument, flag, policy, provenance or preflight failure.
16. Activation tests exhaust the dual-flag truth table and adversarial values,
    prove absent-pair equivalence to exact V24, authenticate the predecessor,
    prove no partial branch, and verify rollback at every composition stage.
    Source scans prove the current V24 files and installed V31 fixture are not
    changed and the Google tool is absent from the default V24 declaration set.
17. Build, package, install, uninstall, installed-runtime, owner-runtime live
    activation and real Google OAuth/provider tests are excluded from this
    implementation and remain Gate C blockers. A later candidate must separately
    prove package inclusion, installed bootstrap/launcher selection, disabled
    equivalence, enabled startup, lifecycle cleanup and rollback to its measured
    predecessor. Real provider acceptance requires separate owner consent and
    cannot inherit a source/fake verdict.
18. Engine/model selection, voice, Orb/HUD, microphone, Gemini, mission store,
    memory, Microsoft Graph/DayOps, other tools/policies, current V24 source and
    installed V31 behavior remain unchanged. This story authorizes no real
    browser/provider call, build, package, install, uninstall, shortcut change,
    signing, release, commit, push, PR or deployment.

## Tasks / Subtasks

- [x] Close the source-development provenance prerequisite (AC: 1, 18).
  - [x] Record and independently recompute exact sizes, hashes and repository
    paths for every 1.0/1.1 dependency.
  - [x] Obtain conditional `@architect` GO for aggregate
    `0502ad2243d1d4b8d23fd032ccd0c4cff0c58c9940c0c635cd10228e664fecce`.
  - [ ] Keep Git/pre-PR provenance open until separately authorized tracking of
    the exact seven dependencies and manifest; do not stage, commit or push.
  - [ ] Keep build/install/provider/live/release provenance as later independent
    candidate-bound gates.
- [x] Implement the isolated live adapter and declaration (AC: 2, 3, 7-13).
  - [x] Add one `google_workspace` declaration and strict five-action schema.
  - [x] Delegate all operations to the accepted host service; add only the
    minimal host read surface needed to preserve existing connector contracts.
  - [x] Add typed redacted results, receipts and mandatory post-verification.
- [x] Add host-owned policy integration (AC: 8-13).
  - [x] Bind connect/disconnect to exact consequential decisions.
  - [x] Permit autonomous reads only inside the active trusted owner scope.
  - [x] Prove no model approval claim, global bypass or scope expansion exists.
- [x] Implement lifecycle-safe live composition (AC: 4-7, 13, 16).
  - [x] Add strict canonical dual-flag parsing before Google imports/side effects.
  - [x] Own one service instance across activation and every rollback/shutdown.
  - [x] Preserve exact V24 fallback and fail closed on every partial state.
- [x] Add the dedicated activation/bootstrap/launcher branch (AC: 4-7, 16, 18).
  - [x] Authenticate the exact V24 predecessor from the approved baseline.
  - [x] Add new Google-specific activation, bootstrap and launcher files only;
    do not edit the current V24 files or installed V31 tree.
- [x] Implement source activation composition rollback (AC: 7, 13, 14, 16-18).
  - [x] Keep the new branch unpublished until every source composition
    prerequisite succeeds.
  - [x] Inject failures at each construction, registration and cleanup boundary
    and prove exact V24 object-graph restoration.
  - [x] Do not implement or test an installer, package selector, installed-root
    transaction, shortcut/registry mutation or release selection.
- [ ] Complete implementation verification (AC: 1-18).
  - [x] Run focused live-tool/policy/lifecycle tests and all 1.0/1.1 tests.
  - [x] Run activation/default-off/V24 equivalence and composition fault tests.
  - [x] Run combined Goal/Agent Operations and Event Analytics regressions.
  - [x] Run Ruff and Python compilation for exact changed files; document npm
    gates as inapplicable if the Onyx subtree still has no `package.json`.
  - [ ] Obtain independent `@architect` contract review and `@qa` verdict.

## Failure and rollback contract

- Failure before the host/provider attempt is `Denied`, has no Google/provider
  side effect and restores the exact predecessor selection.
- Any ambiguity after browser/provider dispatch or local consequential mutation
  is `UnknownOutcome`; blind retry is prohibited.
- Activation rollback unregisters only the new tool, closes only resources owned
  by this branch and restores the exact predecessor object graph.
- Disabling the flags never deletes existing Google metadata, grants, vault
  records or owner data.
- Failed cleanup cannot replace the primary failure or create a false success.

## Evidence boundaries

| Gate | Minimum evidence | Does not prove |
|---|---|---|
| Source baseline | Exact seven-file local byte snapshot, fixed aggregate and architecture GO | Git ancestry, PR, runtime, provider or installation |
| Git/pre-PR provenance | Later authorized tracking of exact dependencies plus manifest and rerun gates | Package, installation, provider or release |
| Source | Focused/adversarial tests, combined regressions, lint/compile | Installed behavior or Google account |
| Activation | Dual-flag matrix, V24 byte/equivalence proof, lifecycle rollback | Packaged selection |
| Real installed | Blocked Gate C; later candidate-bound build/install/rollback/cleanup evidence | Provider correctness |
| Provider | Later owner-consented Google OAuth/read/revoke receipts | Cross-platform or release readiness |

Evidence never inherits between rows. A fake, monkeypatch, source test or copied
installed fixture must be labelled and cannot be presented as native/provider
acceptance.

## Dev Notes

### Required reuse

- `core/google_workspace_connector_v1.py` remains the only Google provider
  contract and owns OAuth, budgets, Gmail/Calendar GETs, CAS and result receipts.
  [Source: `docs/stories/ONYX-GWS-1.0.0.md`]
- `core/google_workspace_host_v1.py` remains the only production host service
  and owns native authority, loopback, lifecycle and service-level operations.
  [Source: `docs/stories/ONYX-GWS-1.1.0.md#scope-and-dependency`]
- `core/permission_broker.py` is the current host-owned decision boundary;
  model-supplied approvals are ignored. Integration must be additive and cannot
  weaken existing tool policies. [Source: `core/permission_broker.py` module
  contract and model-tool policy tables]
- `core/onyx_live_activation_v24.py` plus its V24 bootstrap and launcher are the
  current source predecessor surfaces and must remain unchanged. The installed
  product remains V31. [Source: `docs/onyx/CURRENT_RELEASE_STATUS.md`]

### Suggested implementation surfaces

The architecture permits new isolated files such as:

- `core/google_workspace_live_v1.py` for declaration, adapter, policy binding,
  audit projection, receipts and post-verification;
- `core/onyx_live_activation_google_workspace_v1.py` for the dedicated branch;
- `scripts/bootstrap_onyx_live_google_workspace_v1.pyw` and
  `scripts/launch_onyx_live_google_workspace_v1.pyw`;
- focused `tests/test_google_workspace_live_v1.py`, activation and transaction
  rollback test modules.

These paths are implementation guidance, not permission to edit current V24,
packaging, build, installer, installed V31 or release files. The implementation
agent must replace this suggested list with the exact changed File List.

### Testing rules

- Use explicit injected providers/transports only in source tests.
- Test every flag/policy/lifecycle/provider boundary before any happy path.
- Assert zero side effects, not merely an expected return value.
- Capture byte hashes of the current V24 source files before and after tests.
- Never print/persist credentials, tokens, authorization URLs/codes/state,
  PKCE, raw identities, Gmail queries or message/event bodies in test output.
- No existing assertion may be deleted or weakened to produce a green result.
- No repository-wide cleanup is authorized; preserve unrelated dirty/untracked
  user work.

### Project structure note

The AEXOS root configuration points to framework/architecture documents that do
not exist under the configured root. This story therefore uses the explicit Vega
handoff, accepted GWS stories and current Onyx source/release documents as its
bounded sources. This configuration drift must not be represented as completed
architecture documentation.

## 🤖 CodeRabbit Integration

### Story Type Analysis

**Primary Type:** Integration  
**Secondary Type(s):** Security, Architecture, CLI  
**Complexity:** High — model tool, policy, live activation, service lifecycle
and source-composition rollback cross multiple trust boundaries.

### Specialized Agent Assignment

**Primary Agents:**

- `@dev` — implementation and pre-commit review
- `@architect` — provenance, activation, policy and source-composition contract gate

**Supporting Agents:**

- `@qa` — independent adversarial verification and exclusive quality verdict
- `@devops` — inactive until a later authorized PR/build/install/release stage

### Quality Gate Tasks

- [x] Pre-Commit (`@dev`): bounded uncommitted implementation self-reviewed;
  Ruff, compilation, focused and combined source gates passed.
- [x] Architecture/Security (`@architect`): GO for v1.2.6 source-only Gate A
  against exact aggregate `0502ad2243d1d4b8d23fd032ccd0c4cff0c58c9940c0c635cd10228e664fecce`.
- [x] QA (`@qa`): GO for focused, adversarial and combined v1.2.6 source-only
  evidence.
- [x] Reliability: GO for replay-audit durability, one-shot rollback ordering,
  retry semantics and failure-closed behavior in the v1.2.6 source boundary.
- [ ] Pre-PR (`@devops`): not authorized in this story.
- [ ] Pre-Deployment (`@devops`): not authorized in this story.

### Self-Healing Configuration

**Expected Self-Healing:**

- Primary Agent: `@dev` (light mode)
- Max Iterations: 2
- Timeout: 15 minutes
- Severity Filter: CRITICAL only

**Predicted Behavior:**

- CRITICAL issues: repair within the approved story scope and rerun all gates.
- HIGH issues: document and return to architecture/QA; do not widen scope.
- MEDIUM/LOW issues: record according to the reviewing gate.

### CodeRabbit Focus Areas

- Unique declaration and strict action/argument schemas.
- Consequential versus autonomous-read policy with exact owner scope.
- Dual-flag/default-off equivalence and no partial activation.
- Lifecycle cleanup, audit redaction, receipts and post-verification.
- Source composition rollback semantics and exact V24/V31 preservation.
- Provenance of every dependency and absence of hidden untracked inputs.

## Change Log

| Date | Revision | Description | Author |
|---|---:|---|---|
| 2026-08-09 | Draft 0.1 | Initial default-off Windows live-wiring story with provenance blocker | Chronos (`@sm`) |
| 2026-08-10 | Architecture 0.2 | Exact seven-file aggregate independently reproduced; conditional GO for source-only implementation with pre-import manifest verification; Git/PR/build/install/provider/live/release remain NO-GO | Vega (`@architect`) |
| 2026-08-10 | 0.3.0 | PO validation GO (9/10); Status set to Ready for Development — Source-only conditional; install/fake-install implementation removed from Gate A | Themis (`@po`) |
| 2026-08-10 | 1.2.0 | Source-only default-off Google Workspace tool, policy, lifecycle, provenance gate, dedicated activation branch and rollback tests implemented; moved to Ready for Review | Vulcan (`@dev`) |
| 2026-08-10 | 1.2.1 | Independent NO-GO findings repaired: authenticated captured-byte loading, strict projections and semantic audit, identity-CAS policy ownership, transactional lifecycle/drain/retry behavior and adversarial subprocess coverage; returned to Ready for Review | Vulcan (`@dev`) |
| 2026-08-10 | 1.2.2 | Second source-only repair closed: authenticated runtime closure, production-only controller construction, dedicated enabled-only HMAC audit/idempotency store, redacted durable read replay, failure-atomic policy leases, linearizable lifecycle and expanded adversarial probes; returned to Ready for Review | Vulcan (`@dev`) |
| 2026-08-10 | 1.2.3 | Third source-only repair closed: authenticated replay verification, action/argument idempotency binding, fully captured and post-execution-verified V24/local closure, retryable construction compensation, closure-private controller authority, clean exception topology, exact booleans and reconciliation digests; returned to Ready for Review | Vulcan (`@dev`) |
| 2026-08-10 | 1.2.4 | Fourth source-only repair closed: real default-off and enabled script startup, one controller-owned persistent provenance session, authenticated full local lazy-import authority, internal-only component construction, separate exactly-once denial audit, exact output types and approved same-id retry; returned to Ready for Review | Vulcan (`@dev`) |
| 2026-08-10 | 1.2.5 | Fifth source-only repair closed: service boundary is constructed before publication, continuous source-session health and retryable provenance cleanup are enforced, denial identity is attempt-trace exact, launcher primary errors survive three rollback failures, and default-off V24 traversal is covered by an explicitly controlled source harness; returned to Ready for Review | Vulcan (`@dev`) |
| 2026-08-10 | 1.2.6 | Sixth source-only repair closed: every approved fresh/replay trace receives a separate authenticated immutable event without duplicating provider dispatch, and successful one-shot V24 rollback is never repeated when later source-session cleanup needs retry; returned to Ready for Review | Vulcan (`@dev`) |
| 2026-08-10 | Independent Gate A review | Architecture, QA and Reliability each issued GO for the v1.2.6 source-only boundary; Status set to Done — Source-only Gate A Approved; Gate B/C remain NO-GO | Independent reviewers |

## Dev Agent Record

### Agent Model Used

GPT-5.6 (Vulcan `@dev`)

### Debug Log References

- `python -m pytest -q --tb=short --basetemp=.codex-tmp/pytest-gws-124-focused-final tests/test_google_workspace_live_v1.py tests/test_onyx_live_activation_google_workspace_v1.py` — 91 passed, including real default-off and enabled bootstrap/launcher/controller subprocesses, double-preflight rejection and restoration, poisoned meta-path probes, authenticated lazy loads for main, bare memory and launchers V19-V23, separate denial audit and exact string-subclass rejection.
- `python -m pytest -q --tb=short --basetemp=.codex-tmp/pytest-gws-124-regression-final tests/test_google_workspace_connector_v1.py tests/test_google_workspace_host_v1.py tests/test_google_workspace_live_v1.py tests/test_onyx_live_activation_google_workspace_v1.py tests/test_goal_agent_operations_v1.py tests/test_event_analytics_v1.py tests/test_operational_goals_v1.py` — 327 passed, 4 skipped.
- `python -m pytest -q --tb=short --basetemp=.codex-tmp/pytest-gws-124-permission tests/test_regressions.py -k "permission or audit"` — 6 passed, 99 deselected.
- `python -m pytest -q --tb=short --basetemp=.codex-tmp/pytest-gws-124-semantic tests/test_control_plane_v5_adversarial.py -k "audit"` — 173 passed, 119 deselected.
- Ruff on the exact nine changed Python/product-test files — all checks passed.
- `py_compile` on the exact nine changed Python/product-test files — passed.
- Root npm gates are inapplicable to the Onyx subtree because `Onyx/package.json` is absent.
- A first combined run without `--basetemp` hit 58 fixture setup errors because the global Windows pytest temp directory denied access; the identical suite passed with repository-local `.codex-tmp`.
- `python -m pytest -q --basetemp .codex-tmp/pytest-gws-v125-a tests/test_onyx_live_activation_google_workspace_v1.py` — 49 passed; covers six transactional install seams, service-first publication, continuous source-session attestation, retained finder/module/controller cleanup authority, launcher primary-plus-three-rollback failure semantics, no free captured-loader seam and controlled default-off V24 traversal.
- `python -m pytest -q --tb=short --basetemp .codex-tmp/pytest-gws-v125-focused-final tests/test_google_workspace_live_v1.py tests/test_onyx_live_activation_google_workspace_v1.py` — 97 passed.
- `python -m pytest -q --basetemp .codex-tmp/pytest-gws-v125-b tests/test_google_workspace_connector_v1.py tests/test_google_workspace_host_v1.py tests/test_google_workspace_live_v1.py` — 230 passed, 4 skipped.
- `python -m pytest -q --tb=short --basetemp .codex-tmp/pytest-gws-v125-regression tests/test_google_workspace_connector_v1.py tests/test_google_workspace_host_v1.py tests/test_google_workspace_live_v1.py tests/test_onyx_live_activation_google_workspace_v1.py tests/test_goal_agent_operations_v1.py tests/test_event_analytics_v1.py tests/test_operational_goals_v1.py` — 333 passed, 4 skipped.
- `python -m pytest -q --tb=short --basetemp .codex-tmp/pytest-gws-v125-permission tests/test_regressions.py -k "permission or audit"` — 6 passed, 99 deselected.
- `python -m pytest -q --tb=short --basetemp .codex-tmp/pytest-gws-v125-semantic tests/test_control_plane_v5_adversarial.py -k audit` — 173 passed, 119 deselected.
- Ruff and `py_compile` on the exact nine changed Python/product-test files — passed.
- `python -m pytest -q --tb=short --basetemp .codex-tmp/pytest-gws-v126-focused-final tests/test_google_workspace_live_v1.py tests/test_onyx_live_activation_google_workspace_v1.py` — 99 passed.
- `python -m pytest -q --tb=short --basetemp .codex-tmp/pytest-gws-v126-regression-final tests/test_google_workspace_connector_v1.py tests/test_google_workspace_host_v1.py tests/test_google_workspace_live_v1.py tests/test_onyx_live_activation_google_workspace_v1.py tests/test_goal_agent_operations_v1.py tests/test_event_analytics_v1.py tests/test_operational_goals_v1.py` — 335 passed, 4 skipped.
- `python -m pytest -q --tb=short --basetemp .codex-tmp/pytest-gws-v126-permission tests/test_regressions.py -k "permission or audit"` — 6 passed, 99 deselected.
- `python -m pytest -q --tb=short --basetemp .codex-tmp/pytest-gws-v126-semantic tests/test_control_plane_v5_adversarial.py -k audit` — 173 passed, 119 deselected.

### Completion Notes List

- Added one exact `google_workspace` declaration and strict action-specific schema.
- Added exact dual-flag selection and a stable, regular-file, seven-dependency manifest verifier that runs before Google imports.
- Kept default-off selection on the V24 bootstrap path without manifest or Google module access.
- Added owner-bound policy envelopes, consequential approval proof, autonomous read-only actions, redacted audit pseudonyms, normalized receipts and mandatory post-verification.
- Added transactional source composition with failpoints, service ownership, protected dispatch, exceptional/normal cleanup and exact owned rollback.
- Replaced import-based enabled-path execution with authenticated captured-byte compile/exec, stable handle/path snapshots, post-execution code seals and preloaded/meta-path/path-swap rejection; launcher failures no longer expose raw tracebacks.
- Added exact RFC3339/order checks, output allowlists, receipt/status/generation post-verification, pre-provider `Denied` preservation and post-worker `UnknownOutcome` classification without retry.
- Added one durable idempotent semantic action record, trace propagation, redacted identity/result/receipt digests and a decision-only broker seam that preserves existing broker behavior without duplicate audit rows.
- Added identity-CAS policy/declaration ownership, exact Phase 6/config/connector attestation, task/worker drain, retryable rollback-pending cleanup and service/instance construction compensation.
- Direct-loaded and hash-pinned the complete enabled runtime closure, including paths, default audit, permission broker, native vault, connector, host, live adapter and the dedicated audit store; rejected preloaded closure members and partial module publication.
- Moved Google audit/idempotency persistence completely out of the default audit schema into an enabled-only SQLite store authenticated by a stable native-vault HMAC key; removed the obsolete default-store Google APIs.
- Added durable reservation/replay/pending-recovery semantics. Read replay persists only bounded projection proofs and never mailbox/calendar content; duplicate actions do not redispatch the provider.
- Added explicit probes for public-constructor injection, failure-atomic policy registration, unhealthy consequential audit, mutable activation globals, fake preloaded activation, poisoned native vault, secret-free exception context and retryable rollback.
- Authenticated every replay against the exact current HMAC key, canonical contract/result, schema, state, action, argument, binding and event hash before allowing a replay; wrong-key, row/schema tamper and logical-action collisions now remain `UnknownOutcome` with zero provider dispatch.
- Bound durable reservation identity to exact binding, action, canonical argument digest and idempotency digest only after argument validation and policy authorization; same-key action or argument drift fails closed.
- Expanded the authenticated closure manifest to 704 local source modules and kept one controller-owned finder authoritative for the full lifecycle; the real probe loaded 170 modules including `main`, bare `memory` and launchers V19-V23, rejected preloaded/unmanifested local imports and post-execution-verified captured functions/classes.
- Preserved partially constructed service, audit store, executor and instance references when cleanup fails, blocked reuse of partial state and proved retryable rollback releases the exact retained objects before predecessor rollback.
- Removed the global controller-construction seam, pinned V23 alongside V24, enforced exact built-in booleans, returned the exact reservation idempotency digest on worker errors/timeouts and ensured raised public cleanup/rollback failures have physically empty cause/context chains.
- Removed public component/capability construction seams: both the controller and `activate_main` accept only an optional environment, create the provenance session internally and retain it through rollback.
- Added an append-only HMAC-authenticated `denied_attempts_v1` namespace outside provider idempotency; repeated denials create one row and a later approved retry with the same logical identity can reserve and dispatch exactly once.
- Enforced exact built-in string/tuple/boolean types for host status, scopes and provider receipts, including adversarial string-subclass rejection.
- Proved the default-off path delegates through the authenticated V24 scripts and the enabled bootstrap authenticates its launcher and activation; v1.2.5 narrows the end-to-end terminal-smoke claim to an explicitly controlled source-only harness.
- Preserved the pinned 1.0/1.1 aggregate and V24 activation/bootstrap/launcher bytes; no installer, package, installed V31, provider, commit, staging, push or release action was performed.
- Self-review v1.2.4 was superseded by the v1.2.5 and v1.2.6 records in `plan/self-critique-ONYX-GWS-1.2.0.json`; independent v1.2.6 review is now complete.
- Made startup publication transactional: the production service, audit store, live adapter and single-worker executor now all exist before declaration, policy, marker or installed-state publication; construction cleanup remains controller-owned and retryable.
- Added a continuous authenticated source-session health fence before install stages, host preflight, instantiation, dispatch, lifecycle and rollback, including exact finder precedence, owned module identity, source seal, path and runtime code seal checks.
- Allowed only the exact three authenticated mutations performed by the frozen Windows V24 install (`main`, `ui`, `core.phase11_live_mission_v1`) to establish the post-install runtime seal; any other mutation set fails closed.
- Retained the active finder/session or activation controller when cleanup ownership drifts, exposed bounded retry handles, and proved recovery after finder restoration or foreign-module replacement removal.
- Removed the free captured-module execution/loading seams; captured authority remains encapsulated by the controller-owned source session.
- Bound denial idempotency to the attempt trace so each denied attempt is recorded exactly once while a later separately traced approved retry can still reserve and dispatch the logical action.
- Preserved the primary sanitized launcher failure after three bounded rollback failures and recorded cleanup-pending only as secondary evidence.
- The default-off end-to-end script test traverses the real authenticated V24 bootstrap/launcher chain but replaces the terminal component smoke with an explicitly labeled source-only controlled exit. It is not evidence of a frozen binary, installed runtime or provider readiness.
- The enabled source-only harness constructs the service boundary, instantiates the controller-owned host and exercises the protected status dispatcher without provider traffic. Production host provisioning and installed/native/provider evidence remain outside Gate A.
- Self-review v1.2.5 was superseded by the v1.2.6 record in `plan/self-critique-ONYX-GWS-1.2.0.json`; independent v1.2.6 review is now complete.
- Added the separate append-only HMAC-authenticated `approved_attempts_v1` namespace. Fresh completion and each current replay trace bind action, argument/idempotency digests, trace, fresh/replay classification, logical event hash and redacted result digest while one logical row and one provider dispatch remain authoritative.
- Made replay audit a pre-return gate: insertion, readback and HMAC verification must succeed for the current trace; any failure returns `UnknownOutcome`, preserves the completed logical result and never redispatches the provider.
- Made cleanup phases explicitly one-shot after success. In particular `_base_started` is cleared immediately after successful V24 rollback and `_source_session_closed` records completed provenance cleanup, so a later source-close retry cannot call V24 twice.
- Added a non-repeatable V24 rollback probe: first source close fails with `rollback_pending` and one base call; the retry closes only the source session and reaches `rolled_back` with the base call count still one.
- Self-review v1.2.6 is recorded in `plan/self-critique-ONYX-GWS-1.2.0.json`; Architecture, QA and Reliability independently issued GO for source-only Gate A.

### File List

- `core/google_workspace_live_v1.py` (new governed live adapter and declaration)
- `core/google_workspace_audit_v1.py` (new enabled-only authenticated audit and durable idempotency store)
- `core/onyx_live_activation_google_workspace_v1.py` (new provenance-gated V24 composition)
- `core/permission_broker.py` (backward-compatible decision-only authorization and identity-owned policy leases)
- `core/tool_audit.py` (immutable Google Workspace semantic audit contract and verification)
- `scripts/bootstrap_onyx_live_google_workspace_v1.pyw` (new default-off source bootstrap)
- `scripts/launch_onyx_live_google_workspace_v1.pyw` (new source launcher)
- `tests/test_google_workspace_live_v1.py` (new adapter/policy/audit/post-verification tests)
- `tests/test_onyx_live_activation_google_workspace_v1.py` (new provenance/default-off/lifecycle/rollback tests)
- `plan/self-critique-ONYX-GWS-1.2.0.json` (development self-review evidence)
- `docs/stories/ONYX-GWS-1.2.0.md` (task, Dev Record, Change Log and File List update)

## QA Results

**GO — v1.2.6 source-only Gate A.**

QA accepted the exact current source boundary with `99 passed` focused,
`335 passed, 4 skipped` combined regression, `6 passed, 99 deselected` for
permission/audit regression and `173 passed, 119 deselected` for semantic audit.
Ruff and `py_compile` also passed on the exact nine changed Python/product-test
files. This verdict does not cover Gate B or Gate C.

## Architecture Review Results

**GO — v1.2.6 source-only Gate A against exact aggregate
`0502ad2243d1d4b8d23fd032ccd0c4cff0c58c9940c0c635cd10228e664fecce`.**

All seven scoped dependency sizes and SHA-256 values were independently
recomputed from `C:\MAAX_Assistant\Onyx`; the documented canonical aggregate was
reproduced exactly. This digest pin is sufficient to detect dependency drift for
bounded local source development when the enabled activation path verifies it
before Google imports. It is not independent authentication or Git provenance.
Architecture accepted the final v1.2.6 captured-source composition, continuous
source-session attestation, service-first publication and exact V24 preservation.
Gate B Git/pre-PR provenance and Gate C build/package/install/provider/live/
release remain NO-GO until their separately authorized evidence is complete.

## Reliability Review Results

**GO — v1.2.6 source-only Gate A.**

Reliability accepted the authenticated per-trace fresh/replay audit events, zero
provider redispatch after replay-audit failure, retryable cleanup ownership and
the non-repeatable V24 rollback probe. The verdict is bounded to source-only
Gate A; it provides no installed-runtime, provider or release evidence, and
Gate B/C remain NO-GO.
