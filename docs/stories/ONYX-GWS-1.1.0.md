# ONYX-GWS-1.1.0 - Google host authority, native vaults, OAuth loopback and CLI

## Status

**Done — Windows Source/Native-Host Approved**

Implementation, architecture review and independent QA are complete for the
isolated Windows source/native-host scope below. Architecture and QA are GO for
that boundary only.
This story authorizes no tool declaration, policy-broker integration, live
activation, bootstrap/launcher change, package, install, provider acceptance or
release. Those concerns remain reserved for a later explicitly approved story.

## Executor Assignment

```yaml
executor: "@dev"
quality_gate: "@architect"
quality_gate_tools:
  - focused source contract tests
  - cross-process and native-vault host harnesses
  - OAuth loopback adversarial tests
  - independent security and QA review
```

## Story

**As the** Onyx owner,  
**I want** a default-off Google Workspace host service with native-vault-backed
authority, bounded OAuth loopback and CLI-first operations,  
**so that** Gmail and Google Calendar can be configured and tested through an
explicit source/host boundary before any tool, live runtime, installed product
or release integration is considered.

## Scope and dependency

This story succeeds `ONYX-GWS-1.0.0`, whose `sqlite.v3/FileSeal.v2` connector
contract is Done for source evidence only. It supplies the host-side dependencies
that the connector deliberately left injected:

- `NativeGoogleMetadataGenerationAnchorV1`;
- a native-vault root secret and domain-separated key derivation;
- configuration, token and pending-authorization vault adapters;
- an exact `127.0.0.1` OAuth loopback receiver;
- the default-off `GoogleWorkspaceHostServiceV1` factory; and
- CLI commands `status`, `configure`, `connect`, `disconnect`, `test-gmail` and
  `test-calendar`.

The service and CLI remain isolated source surfaces. No import or call is added
to `main.py`, activation versions, bootstrap scripts, launchers, tool registries,
permission/policy brokers, packaging or release selectors in this story.

## Acceptance Criteria

1. A new, versioned host module provides
   `NativeGoogleMetadataGenerationAnchorV1` implementing the existing
   `GoogleMetadataGenerationAnchorV1.read()` and `compare_and_swap()` protocol.
   It binds one canonical Google metadata store reference to one pseudonymous
   owner/workspace/provider/account scope, accepts only `None` or non-negative
   63-bit generations, serializes cooperating Onyx processes through a bounded
   host lease, performs native-vault write/readback verification and fails closed
   on missing, malformed, stale, conflicting or cross-binding state.
2. The implementation reuses the native backends in `core/native_vault.py` and
   the host-lease patterns already established by `core/owner_profile_v8.py` on
   Windows and `core/posix_owner_authority_v1.py` on macOS/Linux. It introduces
   no plaintext file, SQLite, environment, command-line or in-memory production
   fallback for anchor, root key, token or pending-authorization secrets.
3. The anchor contract states its real trust limit in code documentation, CLI
   status and evidence: lease plus readback provides CAS only among cooperating
   Onyx processes. Windows Credential Manager, macOS Keychain and Linux Secret
   Service do not by themselves prove a hardware monotonic counter or rejection
   of OS backup/restore, privileged replacement or vault rollback. The adapter
   must not claim administrator resistance, hardware backing, universal
   non-replayability or stronger atomicity than the observed backend provides.
4. Explicit `configure` provisioning creates one random 32-byte Google root
   secret in a versioned native-vault namespace, verifies the round trip and
   derives purpose-specific keys through a documented domain-separated KDF.
   Separate derivation domains exist at minimum for metadata anchor
   authentication, identity pseudonymization, configuration authentication,
   token authentication and pending-authorization authentication. Provisioning
   is idempotent, race-safe, never silently rotates or overwrites an existing
   root binding and exposes no key material.
5. Configuration, token and pending-authorization adapters satisfy the exact
   existing connector protocols. Native-vault records use versioned,
   pseudonymous service/account aliases and strict schemas, maximum byte limits,
   binding authenticators and constant-time comparisons. Raw owner/workspace
   identifiers, account email, client configuration, tokens, authorization code,
   PKCE verifier and OAuth state never appear in aliases, logs, tracebacks,
   receipts or status output. Token CAS/delete and pending consume are serialized
   under the same scoped host lease and verified by readback.
6. A loopback receiver binds only an ephemeral or explicitly configured port on
   literal `127.0.0.1`; it never binds `0.0.0.0`, `::`, a LAN address or a public
   interface. It accepts one exact `GET /oauth2/callback` request, rejects other
   methods/paths, duplicate or forbidden query fields, oversized request line or
   headers, fragments/userinfo/host drift and non-loopback callbacks, emits
   bounded cache-disabled browser text, and closes its socket and worker on
   success, denial, deadline, cancellation or exception.
7. OAuth callback handling preserves the connector's existing PKCE, state,
   binding, exact redirect and single-consume contracts. The receiver has a
   bounded monotonic deadline no longer than the pending authorization expiry;
   timeout or cancellation consumes no new provider attempt, while a callback
   accepted for token exchange cannot be replayed. Native/provider exceptions
   are translated to fixed secret-free public errors with empty cause and
   context.
8. `GoogleWorkspaceHostServiceV1` is a narrow composition/service boundary for
   the 1.0 connector, the host anchor, pseudonymizer, configuration/token/pending
   vaults, loopback receiver and injected HTTP/browser/clock ports. Its factory
   returns `None` unless the exact `GoogleWorkspaceFeatureGateV1(True)` and a
   complete explicit host configuration are supplied. No production path may
   inject test doubles; tests may do so only through explicit source seams.
9. Default-off is exact and side-effect free. With a false gate, absent opt-in or
   incomplete configuration, the factory constructs no connector or listener,
   opens no browser, performs no provider/network request and creates no Google
   metadata, seal, journal, lock or vault record. Importing the host module and
   invoking `status` in the disabled state are provider-free.
10. A CLI-first entry point exposes exactly `status`, `configure`, `connect`,
    `disconnect`, `test-gmail` and `test-calendar`. Inputs use arguments or
    interactive hidden entry as appropriate, never accept OAuth tokens,
    authorization codes, PKCE material or root keys from environment/arguments,
    and reject unknown commands/options. Every command has bounded execution and
    deterministic exit codes. Machine-readable output is strict, versioned JSON;
    human output is a projection of the same redacted result.
11. `status` reports only bounded non-secret facts: enabled/configured/connected
    state, supported backend, pseudonymous binding digest, anchor generation and
    health, exact read-only scope set, pending-loopback state and last redacted
    reconciliation outcome. `configure` changes native host configuration only.
    `connect`, `disconnect`, `test-gmail` and `test-calendar` delegate to the
    bounded host service; they do not bypass connector budgets, identity checks,
    token CAS, revoke uncertainty or GET-only Gmail/Calendar restrictions.
12. Source tests for `connect`, `disconnect`, `test-gmail` and `test-calendar`
    use injected transports/browser/clock/loopback harnesses only. This story
    does not authorize opening a real browser, contacting Google, enrolling the
    owner's account or recording provider acceptance. A later owner-consented
    provider gate must remain separately identifiable from source evidence.
13. Anchor mismatch, root-key loss/rotation, copied vault records, copied
    DB/seal, malformed config/token/pending records, stale token CAS, pending
    replay, callback deadline, listener bind failure, lock timeout, concurrent
    configure/connect/disconnect and post-provider uncertainty produce
    deterministic fail-closed results. Pre-attempt failures are denied without
    provider traffic; any indeterminate state after an external attempt remains
    `UnknownOutcome` and is never silently retried.
14. Automated source evidence covers default-off zero-side-effect behavior,
    namespace and KDF separation, strict schemas/limits, anchor and token CAS,
    concurrent processes, OAuth loopback method/path/host/query/size/deadline/
    single-use cases, traceback redaction, socket/handle cleanup and the combined
    Google Workspace + Goal/Agent Operations + Event Analytics regressions. No
    existing assertion is removed or weakened.
15. Windows, macOS and Linux each have a platform-specific host harness using
    the applicable native vault and lease surface. Simulated platform selection
    proves source behavior only. Real Windows Credential Manager, macOS Keychain
    and Linux Secret Service observations are recorded as three independent host
    evidence gates; an unavailable runner/service remains open and does not block
    the other platforms or become a fabricated pass.
16. The engine, voice, Orb/HUD, mission store, memory, Gemini, Microsoft
    Graph/DayOps, permission broker and installed Windows V31 remain untouched.
    This story creates no tool declaration/policy, live activation/wiring,
    bootstrap/launcher integration, package, installer, shortcut, signing,
    release or installed-runtime evidence and performs no commit, push, PR,
    provider call or deployment.

## Tasks / Subtasks

- [x] Implement the bounded host authority (AC: 1-4, 13, 15).
  - [x] Add `NativeGoogleMetadataGenerationAnchorV1` around the existing anchor
    protocol, native vault and platform lease patterns.
  - [x] Add the versioned root-secret namespace and domain-separated key
    derivation without plaintext fallback.
  - [x] Document and surface the cooperating-process CAS and rollback limits;
    reject any stronger unsupported claim.
- [x] Implement native Google vault adapters (AC: 4, 5, 13, 15).
  - [x] Add strict config, token and pending record schemas with bounded bytes,
    pseudonymous aliases, authenticators and readback verification.
  - [x] Implement token compare-and-set/delete and single-consume pending state
    under the scoped host lease.
  - [x] Prove no secret/raw identity disclosure in aliases, output, exceptions,
    tracebacks or durable non-vault files.
- [x] Implement bounded OAuth loopback (AC: 6, 7, 13).
  - [x] Bind literal `127.0.0.1`, validate the exact callback surface and bound
    request/header/response sizes and monotonic deadline.
  - [x] Guarantee single-use completion plus deterministic socket/thread/handle
    cleanup on every exit path.
  - [x] Reuse the Graph OAuth transport/error/secret-handling precedent where it
    is compatible; preserve Google's existing PKCE and callback contracts.
- [x] Implement the isolated host service factory (AC: 8, 9, 11-13, 16).
  - [x] Compose only the 1.0 connector and new host ports in
    `GoogleWorkspaceHostServiceV1`.
  - [x] Seal exact default-off/complete-config behavior and prohibit production
    test doubles.
  - [x] Do not import the factory from runtime activation, tools, UI, bootstrap,
    launchers, packaging or release code.
- [x] Implement the CLI-first surface (AC: 9-13, 16).
  - [x] Add exact `status`, `configure`, `connect`, `disconnect`, `test-gmail`
    and `test-calendar` commands with deterministic exit codes.
  - [x] Derive human and versioned JSON output from one redacted result model.
  - [x] Ensure disabled `status` is provider/artifact free and command tests use
    injected non-provider harnesses only.
- [ ] Complete source quality gates (AC: 13, 14, 16).
  - [x] Run focused host/vault/loopback/service/CLI tests and adversarial
    concurrency/replay/fault-injection tests.
  - [x] Run the combined Google Workspace, Goal/Agent Operations and Event
    Analytics regression set.
  - [x] Run Ruff and Python compilation for changed Python files; run applicable
    repository lint/typecheck/test gates and document genuinely inapplicable
    gates rather than fabricating results.
  - [ ] Run `@dev` pre-commit review, `@architect` contract review and independent
    `@qa` verification; only `@qa` may issue the final quality verdict.
- [ ] Record, but do not conflate, native-host evidence (AC: 3, 15, 16).
  - [x] Record Windows Credential Manager evidence when observed on Windows.
  - [ ] Record macOS Keychain evidence only when observed on native macOS.
  - [ ] Record Linux Secret Service evidence only when observed with a real
    session service on native Linux.
  - [x] Keep missing native runners/services as explicit open host gates; do not
    run provider, installed or release gates in this story.

## Failure and rollback contract

- Before provider attempt, invalid configuration, unhealthy/missing native
  authority, binding drift, stale generation, vault failure, callback denial or
  lock timeout fails closed without provider traffic.
- After an external attempt begins, timeout, response ambiguity, persistence
  failure or lost confirmation remains `UnknownOutcome`; the service does not
  blind-retry or relabel it as a clean denial.
- `disconnect` preserves uncertainty if provider revocation may have occurred but
  local confirmation failed. Destructive local vault deletion does not substitute
  for a confirmed provider outcome.
- Disabling the isolated factory creates no new artifacts and does not delete
  existing Google metadata or vault records. Removal/cleanup is not authorized by
  this story.
- Vault rollback, OS backup restore and privileged replacement remain outside the
  proven CAS guarantee unless independently demonstrated on the exact native
  backend. Such evidence is a host limitation, not a reason to add an insecure
  fallback or claim non-replayability.

## Evidence boundaries

| Gate | Minimum evidence in this story | Does not prove |
|---|---|---|
| Source | Focused/adversarial tests, combined regressions, lint/compile, independent review | Real native vault, Google account, installed product or release |
| Windows host | Real Credential Manager plus native lease/readback/concurrency/cleanup observations | macOS/Linux parity, Google provider or package behavior |
| macOS host | Real Keychain plus native lease/readback/concurrency/cleanup observations | Windows/Linux parity, Google provider or package behavior |
| Linux host | Real Secret Service plus native lease/readback/concurrency/cleanup observations | Windows/macOS parity, Google provider or package behavior |
| Provider | Not authorized in 1.1.0; remains open | Nothing until separately owner-authorized and observed |
| Installed/release | Not authorized in 1.1.0; remains open | Nothing until candidate-bound build/install/release gates pass |

Evidence never inherits between rows. Source fakes and simulated platforms are
labelled as such.

## Dev Notes

### Required reuse and precedents

- `core/google_workspace_connector_v1.py` is the accepted 1.0 connector and
  defines the anchor, pseudonymizer, token, pending, OAuth, budget, status,
  revoke, Gmail and Calendar contracts. Preserve it unless an independently
  reviewed interface correction is unavoidable.
- `core/native_vault.py` is the cross-platform secret primitive and has no
  plaintext fallback. Reuse `SecretReference`/`NativeSecretVault`; do not create
  a second vault abstraction that bypasses its namespace protections.
- `core/owner_profile_v8.py` demonstrates Windows Credential Manager CAS under a
  Windows host lease with write/readback verification. Reuse the pattern, not
  its owner-profile namespaces.
- `core/posix_owner_authority_v1.py` demonstrates Keychain/Secret Service access
  under a POSIX cross-process lease. Reuse its platform/trusted-directory
  patterns without importing owner-profile business semantics.
- `core/phase8_microsoft_graph_oauth_v1.py` is a precedent for bounded OAuth HTTP,
  native token vaulting and error taxonomy. Google uses loopback authorization,
  so Graph device-flow behavior is not copied where the protocols differ.
- `core/paths.py` remains authoritative for writable per-user data roots. No
  mutable artifact belongs in the source/package root of a frozen runtime.

### Suggested implementation surfaces

- New `core/google_workspace_host_v1.py` for authority, KDF, vault adapters,
  loopback receiver and `GoogleWorkspaceHostServiceV1`.
- New `scripts/onyx_google_workspace.py` for the isolated CLI.
- New focused tests under `tests/` for host, loopback, service and CLI behavior.
- Existing connector tests and combined regressions remain unchanged except for
  additive assertions required by an approved interface correction.

These are guidance, not permission to touch runtime activation or release files.
The implementation agent must update the File List to the exact changed files.

### Testing and evidence rules

- Test doubles are accepted only as source evidence and must be visibly injected.
- Native platform tests must report the actual OS/backend observed; monkeypatched
  platform names are not native-host acceptance.
- Provider tests are not run in this story. No owner credential, Google browser
  session or provider call is authorized.
- No test may print or persist secret/token/code/state/PKCE values, and no existing
  assertion may be weakened or deleted for a green result.

## 🤖 CodeRabbit Integration

### Story Type Analysis

**Primary Type:** Security  
**Secondary Type(s):** Integration, Architecture, CLI  
**Complexity:** High - cross-platform vault semantics, concurrency, OAuth
loopback and strict evidence boundaries.

### Specialized Agent Assignment

**Primary Agents:**

- `@dev` - implementation and pre-commit review
- `@architect` - host trust/CAS and composition contract gate

**Supporting Agents:**

- `@qa` - adversarial verification and exclusive quality verdict
- `@devops` - not active in this story; PR/release authority only if later asked

### Quality Gate Tasks

- [x] Pre-Commit (`@dev`): review uncommitted bounded source scope.
- [x] Architecture/Security (`@architect`): GO for the isolated default-off
  Windows source/native-host boundary. This is not a live, installed, provider,
  release or cross-platform approval; native macOS/Linux gates remain open and
  native-vault CAS remains limited to cooperating Onyx processes.
- [x] QA (`@qa`): independently ran focused/adversarial/combined and native
  Windows host gates; verdict GO for the Windows source/native-host boundary.
- [ ] Pre-PR (`@devops`): not authorized in 1.1.0.
- [ ] Pre-Deployment (`@devops`): not authorized in 1.1.0.

### Self-Healing Configuration

**Expected Self-Healing:**

- Primary Agent: `@dev` (light mode)
- Max Iterations: 2
- Timeout: 15 minutes
- Severity Filter: CRITICAL only

**Predicted Behavior:**

- CRITICAL issues: repair within this story's source scope and rerun gates.
- HIGH issues: document and return to architecture/QA; do not widen scope.
- MEDIUM/LOW issues: record according to the reviewing gate.

### CodeRabbit Focus Areas

- Native-vault namespace isolation, key derivation, CAS/lease/readback semantics
  and honest rollback guarantees.
- OAuth listener binding, exact callback, deadlines, single use and cleanup.
- Exact default-off behavior, zero side effects, fixed errors and no secret/raw
  identity disclosure.
- Absence of runtime/tool/activation/bootstrap/package/release changes.

## Change Log

| Date | Revision | Description | Author |
|---|---:|---|---|
| 2026-08-09 | Draft 0.1 | Initial draft | Chronos (`@sm`) |
| 2026-08-09 | PO 0.2 | Validated GO (9/10); narrowed to host authority, vaults, OAuth loopback, CLI and source/native-host gates; Status: Draft to Ready | Themis (`@po`) |
| 2026-08-09 | Baseline | Implemented the isolated host authority, native-vault adapters, loopback service and CLI; Status: Ready for Review | Vulcan (`@dev`) |
| 2026-08-09 | R1 | Repaired security review findings: root-loss marker, redacted OAuth repr/CLI parsing, recoverable vault transactions, bounded loopback/pending lifecycle and service cleanup; Status: Ready for Review | Vulcan (`@dev`) |
| 2026-08-09 | R2 | Repaired R2 blockers: authenticated delete tombstones, whole-operation native lease/close ordering, external state witness, cross-process pending marker, exact 16 KiB token envelopes, safe ancestor creation, CLI closure and factored loopback parsing; Status: Ready for Review | Vulcan (`@dev`) |
| 2026-08-09 | R4 | Repaired R4 blockers: exact native-lease body passthrough, expired pending reconciliation, spawned cross-process CLI status, retryable close lifecycle, external related-state loss detection and pinned metadata-parent identity; Status: Ready for Review | Vulcan (`@dev`) |
| 2026-08-09 | R5 | Repaired R5 blockers: retryable loopback-resource closure, PREPARED/COMMITTED external witness transaction and Windows DELETE-access metadata-directory pin retained for service lifetime; Status: Ready for Review | Vulcan (`@dev`) |
| 2026-08-09 | R6 | Repaired R6 crash-durability blocker: same-parent private temp, bounded write/fsync/close/exact verification, atomic MoveFileExW/os.replace publication, POSIX parent fsync, readback and idempotent managed-temp cleanup with fault/restart coverage; Status: Ready for Review | Vulcan (`@dev`) |
| 2026-08-09 | R7 | Repaired R7 close-ownership blocker: stateful owned temp descriptors, fstat identity/loss classification, parent-pin pending cleanup registry, single close attempt per call, retryable Windows cleanup/pin close, restart orphan cleanup and retained POSIX dirfd durability; Status: Ready for Review | Vulcan (`@dev`) |
| 2026-08-09 | R8 | Repaired R8 descriptor-reuse blocker: every temp/POSIX-dirfd close error irrevocably abandons the numeric descriptor without fstat or retry, records only managed path plus restart-required state, blocks same-process witness mutation, releases independent pins honestly and reconciles only after process restart; Status: Ready for Review | Vulcan (`@dev`) |
| 2026-08-09 | QA R8 | Independent QA PASS: focused `94 passed, 3 skipped`; combined `229 passed, 4 skipped`; targeted R8 close/restart, Atomic 9, prior blockers and disposable native Windows cleanup all passed; Status: Done — Windows Source/Native-Host Approved | Argus (`@qa`) |

## Dev Agent Record

### Agent Model Used

Codex developer subagent operating as Vulcan (`@dev`).

### Debug Log References

- `python -m pytest -q tests\\test_google_workspace_host_v1.py --basetemp=<fresh-workspace-local-dir>` -> 94 passed, 3 explicitly open native-host skips.
- `python -m pytest -q -rs tests\\test_google_workspace_host_v1.py tests\\test_google_workspace_connector_v1.py tests\\test_goal_agent_operations_v1.py tests\\test_event_analytics_v1.py --basetemp=<fresh-workspace-local-dir>` -> 229 passed, 4 skips.
- `python -m pytest -q tests\\test_google_workspace_host_v1.py -k "external_witness_atomic_faults or initial_prepared_atomic" --basetemp=<fresh-workspace-local-dir>` -> 9 passed, 83 deselected; partial-write, flush, close, pre-replace, replace, post-replace, readback, parent-fsync and initial PREPARED failures preserved a valid permanent target and converged on retry without a managed-temp orphan.
- `python -m pytest -q -rs tests\\test_google_workspace_host_v1.py -k "external_witness_atomic_faults or initial_prepared_atomic or persistent_open_temp or temp_close_same_path or temp_close_different_inode or posix_dirfd_same or new_parent_removes" --basetemp=<fresh-workspace-local-dir>` -> 13 passed, 1 explicit POSIX-native skip, 83 deselected; persistent-open close, same-path/same-inode and different-inode descriptor reuse, restart cleanup and atomic fault paths passed without any post-error probe, retry or double-close.
- `python -m pytest -q -s tests\\test_google_workspace_host_v1.py -k "spawned_cli_observes_pending" --basetemp=<fresh-workspace-local-dir>` -> 1 passed, 91 deselected; spawned CLI observed active/cleared pending state and cleanup.
- `python -m pytest -q -rs tests\\test_google_workspace_host_v1.py -k "native_windows" --basetemp=<fresh-workspace-local-dir>` -> 2 passed, 90 deselected; disposable native namespaces were read back and cleaned by the tests.
- `python -m ruff check core\\google_workspace_host_v1.py core\\google_workspace_connector_v1.py scripts\\onyx_google_workspace.py tests\\test_google_workspace_host_v1.py` -> pass.
- `python -m py_compile core\\google_workspace_host_v1.py core\\google_workspace_connector_v1.py scripts\\onyx_google_workspace.py tests\\test_google_workspace_host_v1.py` -> pass.
- `python scripts\\onyx_google_workspace.py status --json` -> exit 0, strict redacted disabled result, no factory/provider/vault call.
- CodeRabbit pre-commit attempt unavailable because the configured WSL host lacks `bash`; no pass was claimed.
- Repository npm gates are not applicable because `C:\\MAAX_Assistant\\Onyx` has no `package.json`.

### Completion Notes List

- [x] PO scope validation completed against the final architecture handoff.
- [x] Runtime/tool/activation/bootstrap/package/release work deferred to a later
  explicitly approved story.
- [x] Native CAS/rollback limitations and platform/provider evidence boundaries
  made explicit.
- [x] Implemented authenticated, recoverable native-vault transactions so both
  connector token fields retain their exact 16 KiB bounds despite the 2 KiB
  native-vault primitive; chunk aliases use the complete payload digest.
- [x] Implemented native root provisioning, six separate KDF domains, anchor
  CAS, config idempotence, token CAS/delete and pending single-consume under a
  shared scoped host lease with readback verification.
- [x] Implemented an exact literal-IPv4 loopback receiver and default-off host
  factory without imports from runtime activation, tools, UI, launchers,
  packaging or release selectors.
- [x] Implemented the exact six-command CLI with versioned redacted JSON,
  human projection and deterministic exit codes; direct disabled status passed.
- [x] Developer focused/combined/lint/compile checks passed. The first combined
  attempt was invalidated by an inaccessible global pytest temp root; the exact
  gate passed using a new workspace-local `--basetemp` without modifying that
  protected external directory.
- [x] Real Windows evidence observed a missing-record Credential Manager read
  plus bounded cross-process native lease conflict/cleanup. A disposable
  diagnostic namespace also proved exact cross-process anchor CAS and verified
  native write/readback/delete cleanup. macOS Keychain and Linux Secret Service
  remain explicit open host gates, not simulated passes.
- [x] Security repair added a root-binding marker that blocks reprovisioning
  after root/marker loss, secret-free OAuth object representations and CLI parse
  failures, separate request/header/body loopback limits with slowloris deadline,
  real pending-loopback status and terminal pending cleanup, recoverable vault
  transactions, service close/context management and hardened metadata-parent
  path checks.
- [x] Third repair added an independently namespaced authenticated state witness
  so simultaneous root/marker loss remains detectable. Simultaneous privileged
  deletion of root, marker and witness remains outside the stated OS-vault trust
  boundary and is not represented as administrator resistance.
- [x] Consequential service operations now retain one reentrant scoped native
  host lease for the entire external operation across sibling services; release
  failures are Denied before mutation, UnknownOutcome after possible mutation,
  and never replace a primary failure. Close cancels the receiver, waits for
  pending tombstone/marker cleanup, and only then closes lease resources.
- [x] Delete/consume uses authenticated recoverable tombstones, pending-loopback
  status is an authenticated sibling-process-visible vault marker, and token
  persistence uses bounded base64 envelopes that preserve exact 16,384-byte
  UTF-8 token values including quotes, controls, NUL and multibyte content.
- [x] CLI parsing keeps unknown command strings out of results, closes every
  constructed service in `finally`, emits one deterministic result even on close
  failure, and the loopback receiver now separates bounded reads from exact
  request parsing without changing its accepted surface.
- [x] Native host lease adaptation now passes through Contract, Denied and
  UnknownOutcome raised by the operation body, translates only acquire/release
  failures and preserves the primary body failure even when release also fails;
  both fake and real underlying lease paths are covered.
- [x] Expired pending markers are authenticated, tombstoned and reconciled before
  a new connection marker is admitted. A spawned Windows CLI process proved
  `pending_loopback=true` while a parent service retained the consequential
  native lease, then `false` after cancellation and cleanup, with native-vault
  delete/readback cleanup of its disposable namespace.
- [x] Service cleanup now has explicit open/closing/closed states. Cleanup or
  lease-close failure leaves a retryable closing state; only successful receiver,
  pending and lease cleanup commits closed.
- [x] The non-secret external witness is a durable PREPARED/COMMITTED transaction:
  PREPARED is fsynced before root/config mutation, COMMITTED occurs only after
  root, config, metadata construction and pinned-parent revalidation. Existing
  PREPARED state never silently reprovisions an absent authority; intact root or
  config crash states can resume deterministically. PREPARED and COMMITTED both
  deny availability if all three vault authority records disappear. Privileged
  deletion of both every vault authority and the external witness remains outside
  the proven boundary.
- [x] OAuth receiver cleanup now uses open/closing/closed state, retains every
  resource whose close failed and permits a real retry. A real loopback listener
  wrapped with one failing close proved the reference and OS socket remain live
  after failure and are closed only by the successful retry; service closed is
  committed only after receiver, pending, parent pin and lease cleanup confirm.
- [x] Windows metadata-parent construction validates every existing ancestor,
  opens the exact directory using `CreateFileW` with DELETE plus
  FILE_READ_ATTRIBUTES, BACKUP_SEMANTICS, OPEN_REPARSE_POINT and share READ/WRITE
  without SHARE_DELETE, validates identity/reparse from the original handle and
  retains it for the service lifetime. Direct Win32 probing established that
  READ_ATTRIBUTES alone allowed rename on this host, while DELETE access caused
  ERROR_SHARING_VIOLATION; the exact post-revalidation/pre-SQLite race now proves
  zero descendant mutation. POSIX source now retains and revalidates an opened
  directory descriptor and uses that same pin for parent fsync, but native macOS
  and Linux observation remain explicit open gates and no simulated host pass is
  claimed.
- [x] External witness publication no longer truncates the permanent target.
  PREPARED creation and PREPARED-to-COMMITTED transition use an exclusive,
  private same-parent managed temp, bounded full write, descriptor flush/close,
  exact canonical temp verification and one atomic publication. Windows uses a
  checked `MoveFileExW(REPLACE_EXISTING | WRITE_THROUGH)` while retaining the
  metadata-parent pin for the entire sequence; POSIX uses `os.replace` followed
  by parent-directory fsync. Exact readback follows publication. Pre-publication
  faults leave the previous valid witness untouched; post-publication ambiguity
  is `UnknownOutcome`, and restart observes the valid published state. Fault
  injection proved retry convergence and no malformed permanent witness or
  surviving managed temp. Native POSIX durability remains subject to its open
  macOS/Linux host gates; no simulated platform pass is claimed.
- [x] Temporary witness ownership uses a strict restart boundary. After any
  temp-descriptor close error, the numeric descriptor is irrevocably abandoned:
  it is set to `None`, never inspected with `fstat`, never retried and never
  passed to `close` again. The parent and process registries retain only the exact
  managed temp path plus `restart_required`; all further witness mutation in
  that process fails with fixed `UnknownOutcome`. Parent/service cleanup may
  release its independently owned Windows pin, but still reports restart-required
  rather than pretending the temp outcome is known. POSIX dirfd close errors use
  the same no-probe/no-retry rule and block a new same-process authority. Tests
  deliberately reused the identical numeric fd for the same path/inode and for
  a different inode; both replacements remained live after parent close. A
  persistently open Windows temp received exactly one close attempt in a child
  process; after process exit let the OS release it, a new authority removed the
  exact managed temp and committed the preserved canonical PREPARED witness.
  Native POSIX same-directory fd-reuse execution remains an explicit skipped host
  gate on Windows, not a simulated pass.
- [x] Architecture gate: GO for Windows source/native-host only. No approval is
  implied for live/tool wiring, packaging, installed V31, provider acceptance,
  macOS/Linux native hosts, release, hardware monotonicity or rollback resistance.
- [x] Independent QA gate: GO for Windows source/native-host only. Focused
  verification completed with `94 passed, 3 skipped`; combined regression with
  `229 passed, 4 skipped`; the targeted R8 close/restart slice, Atomic 9, R5/R6
  blockers and spawned native Windows cleanup all passed. The skipped cases are
  retained as explicit platform gates and are not represented as passes.

### File List

- `core/google_workspace_host_v1.py` (new isolated host authority and service)
- `core/google_workspace_connector_v1.py` (OAuth authorization-start repr redaction and exact token byte-bound preservation)
- `scripts/onyx_google_workspace.py` (new CLI-first source entry point)
- `tests/test_google_workspace_host_v1.py` (new focused/adversarial/host tests)
- `docs/stories/ONYX-GWS-1.1.0.md` (implementation record and evidence)

## QA Results

**PASS / GO — Windows source/native-host boundary only.**

- Compile and Ruff gates passed for the connector, host, CLI and host tests.
- Focused host gate: `94 passed, 3 skipped`.
- Combined host, connector, goal-agent and analytics regression gate:
  `229 passed, 4 skipped`.
- Targeted R8 verification passed the close/restart slice, including same-path
  and same-inode numeric-descriptor reuse without closing the replacement,
  different-inode reuse, persistent-close process restart and managed-temp
  restart cleanup.
- Atomic 9 passed all eight commit fault positions plus initial PREPARED failure;
  the permanent witness remained canonical and retries/restarts reconciled to
  the expected PREPARED or COMMITTED state.
- Prior R5/R6 blockers passed: real listener close retry,
  PREPARED/COMMITTED crash handling, total authority-loss denial, pinned Windows
  metadata-parent race protection and retryable service cleanup.
- Native Windows gates passed for Credential Manager observation,
  cross-process lease exclusion, exact-one-winner spawned anchor CAS, spawned
  CLI pending observation and deletion/readback verification of all tracked
  disposable native references.

This QA verdict does not approve or imply live operation. External gates remain
open for native macOS, Linux and POSIX execution, real Google OAuth/provider
receipts, installed/package acceptance and integrated multiprocess real-provider
revoke/acceptance.

## Architecture Review Results

**GO — Windows source/native-host boundary only.** The default-off host/CLI,
native authority and OAuth lifecycle satisfy the bounded architecture contract.
The adapter proves lease-plus-readback CAS only among cooperating Onyx processes;
it does not prove hardware monotonicity, administrator resistance or immunity to
OS backup/restore and native-vault rollback. No live/tool/policy/package/V31 or
provider integration is approved by this verdict. Native macOS, Linux and POSIX
execution, real Google-provider acceptance, installed-runtime evidence and
integrated multiprocess real-provider revoke remain explicit future gates.
