# ONYX-GWS-1.0.0 - Stabilize Google Workspace V1 authenticated metadata storage

## Status

**Done — Source-only Approved**

Independent QA approved the source-only `sqlite.v3/FileSeal.v2` repair. This
status does not authorize live wiring, build, install or release promotion.

## Requirement source

- Owner direction: continue toward an advanced Onyx while preserving the
  current engine and every existing capability.
- Current regression evidence: **135 passed, 1 platform-conditional skipped,
  0 failed** across
  `tests/test_google_workspace_connector_v1.py`,
  `tests/test_goal_agent_operations_v1.py` and
  `tests/test_event_analytics_v1.py`.
- Existing Google Workspace V1 contract in
  `core/google_workspace_connector_v1.py`: digest-only durable metadata,
  external 32-byte authentication key, authenticated rows/head and an external
  file-container seal.
- Existing focused contract in `tests/test_google_workspace_connector_v1.py`:
  normal same-key reopen succeeds; wrong-key, row, head, schema and container
  tampering fail closed; failed reads do not retain Windows database handles.
- Release boundary: Google Workspace V1 remains default-off and source-only.
  This story does not authorize live activation, real credentials, packaging,
  release promotion or any change to the installed Windows V31 product.

## Acceptance criteria

- [x] 1. Creating the durable store, persisting an accepted grant and reopening
  the same database with the same 32-byte key succeeds and returns the
  previously authenticated `connected` metadata state.
- [x] 2. The authenticated SQLite schema accepts exactly the two declared
  application objects, `google_grants_v1` and `google_grant_head_v1`, with their
  existing exact SQL definitions; any additional, missing, renamed or altered
  `sqlite_master` object fails closed as object-set or schema drift.
- [x] 3. The external seal authenticates the exact final SQLite file container
  produced by every successful durable mutation, without invalidating an
  unchanged normal reopen. The seal remains external, authenticated by the
  supplied key and bound to the intended database container.
- [x] 4. A missing, orphaned, malformed, wrong-key or mismatched external seal,
  including appended/trailing container data and unexpected SQLite sidecars,
  fails closed without returning grant metadata.
- [x] 5. Direct row mutation is rejected by the row-authentication contract;
  head mutation is rejected by the head-authentication contract; schema/object
  drift and whole-container tampering are rejected by their corresponding
  authenticated boundaries. No case is silently repaired or accepted.
- [x] 6. All success and failure paths close SQLite/file handles so the database
  and seal can be removed immediately on Windows after constructor rejection.
- [x] 7. Authentication keys, access tokens, refresh tokens and owner/account
  plaintext do not enter the SQLite database, external seal, exception text or
  test output.
- [x] 8. The complete focused Google Workspace V1 test module passes, including
  normal reopen, exact `sqlite_master`, wrong-key and adversarial tamper cases.
- [x] 9. The combined Google Workspace, Goal/Agent Operations and Event
  Analytics regression set passes with zero failures and without weakening or
  deleting an existing assertion.
- [x] 10. The connector remains default-off/source-only. No live activation,
  credential enrollment, host wiring, packaging artifact, release record or
  installed V31 file is created or changed by this story.

## Tasks / Subtasks

- [x] Diagnose the durable-container authentication ordering and state
  transition (AC: 1, 3, 5).
  - [x] Reproduce the normal create/write/close/reopen sequence with the same
    key and identify why the post-write file differs from its accepted seal.
  - [x] Trace constructor and mutation paths through schema, row, head,
    container and external-seal verification without changing public connector
    behavior.
- [x] Stabilize the exact SQLite object-set boundary (AC: 2, 5).
  - [x] Preserve the existing exact definitions for `google_grants_v1` and
    `google_grant_head_v1`.
  - [x] Enforce equality against the full ordered `sqlite_master` application
    object set so unexpected tables, indexes, triggers or views fail closed.
- [x] Stabilize the external file-container seal lifecycle (AC: 1, 3, 4, 6).
  - [x] Ensure a seal is derived only from the finalized, closed durable
    container and is verified against the same canonical container state on
    reopen.
  - [x] Preserve fail-closed handling for missing/orphan seals, wrong keys,
    malformed manifests, trailing bytes and SQLite sidecars.
  - [x] Ensure temporary connections and handles close on every rejection path.
- [x] Preserve layered tamper detection and data minimization (AC: 4, 5, 7).
  - [x] Verify deterministic rejection for row, head, schema/object-set and
    whole-file tampering without accepting or auto-repairing corrupted state.
  - [x] Verify durable bytes, seal bytes and emitted errors contain no tokens,
    raw owner/account identity or authentication key.
- [x] Complete focused and combined regression validation (AC: 8, 9, 10).
  - [x] Run `tests/test_google_workspace_connector_v1.py` in full.
  - [x] Run the combined Google Workspace, Goal/Agent Operations and Event
    Analytics regression set with zero failures.
  - [x] Confirm zero removed/weakened assertions and record exact commands,
    counts and results in the Dev Agent Record before changing story status.
  - [x] Confirm no activation, credential, package, release or installed-runtime
    surface appears in the implementation diff.
- [ ] Complete review gates before handoff.
  - [x] Pre-Commit (@dev): review the uncommitted database/security change with
    focus on fail-closed behavior, constant-time comparisons, handle closure and
    secret leakage.
  - [x] Quality review (@qa): independently verify focused and combined results
    plus the story checklist; only @qa may issue the quality verdict.
  - [ ] Pre-PR (@devops), if later requested: verify the diff is limited to the
    story file, connector module and focused test module. This story does not
    authorize a push or pull request.
- [x] Repair the independent NO-GO integrity findings.
  - [x] Treat every preexisting path, including zero bytes, as immutable until
    read-only schema, object-set, DB, seal and anchor authentication succeeds.
  - [x] Replace in-place mutation with copy-on-write staged DB+seal,
    authenticated PREPARED journal, durable publication and recovery.
  - [x] Require an injected trusted monotonic generation anchor and reject
    authenticated rollback/replay of the replayable DB+seal pair.
  - [x] Serialize instances/processes with an interprocess lock and verify
    stable file identity/exact bytes before accepting a seal.
  - [x] Require an injected domain-separated HMAC identity pseudonymizer and
    remove raw enumerable identity SHA-256 values from durable metadata.
  - [x] Remove provider-secret exception chaining and add formatted traceback
    coverage plus crash, sidecar, tamper, replay and concurrency adversarials.
- [x] Repair the final snapshot, recovery and durability findings.
  - [x] Bind every `get()` result to one authenticated in-memory SQLite
    snapshot and reject pair/generation changes during the read.
  - [x] Build COW stages from the exact authenticated bytes; revalidate source,
    stage, semantic schema/head and seal generation before PREPARED.
  - [x] Classify the strict trusted anchor before recovery publication; reject
    old journals and confirm CAS by reread before journal removal.
  - [x] Enforce strict anchor and pseudonymizer return types, sanitize their
    failures, and retain PREPARED state for every unknown outcome.
  - [x] Use stable bounded regular-file reads for DB, seal, journal and stages;
    reject links/reparse points and non-canonical stage names.
  - [x] Add a monotonic lock timeout and real Windows FlushFileBuffers plus
    MoveFileExW replace-existing/write-through durability primitives.
  - [x] Sanitize public exception causes/contexts, including JSON/provider
    parsing, and add all final regression probes without weakening assertions.
- [x] Repair the final external-boundary, hardlink and Windows findings.
  - [x] Translate resolver, persister, metadata, pending, anchor,
    pseudonymizer, transport/provider and clock failures to fixed public
    classes/messages with physically empty cause and context.
  - [x] Reject hardlinked DB, seal, journal, stage and lock artifacts using
    lstat/open-no-follow/fstat/lstat identity and single-link checks.
  - [x] Use MoveFileExW with REPLACE_EXISTING and WRITE_THROUGH for both absent
    and existing Windows destinations; flush before and revalidate after.
  - [x] Cover status, connect, refresh, revoke and every injected port boundary
    with secret, `__cause__` and `__context__` assertions.

## QA Results

### Verdict

**PASS / GO — source-only scope**

Independent QA verified the authenticated metadata implementation and the
declared regression boundary on 2026-08-09. No current P0-P2 functional finding
remains within this story's source-only scope. This QA record supersedes the
earlier development-handoff notes that described independent QA as pending.

### Evidence

- Focused Google Workspace suite: **88 passed, 1 platform-conditional skipped,
  0 failed**.
- Combined Google Workspace, Goal/Agent Operations and Event Analytics suite:
  **135 passed, 1 platform-conditional skipped, 0 failed**.
- Explicit external-port, hardlink, Windows atomic-publication and historical
  transaction-regression selection: **13 passed, 0 failed**.
- Python bytecode compilation: **passed**.
- Ruff static validation: **all checks passed**.

### Scope limitations

- The connector, focused tests and this story are currently untracked, so diff
  provenance and assertion-history certification remain unavailable until a
  later authorized repository gate.
- A real host-backed, non-replayable monotonic generation anchor is not yet
  implemented or independently accepted.
- Live wiring, real credentials, packaging, installation and installed-runtime
  validation remain outside this completed story and are not authorized by the
  QA verdict.

## Change Log

- 2026-08-09 — @qa: source-only verdict PASS/GO; status transitioned from
  `Ready for Review` to `Done — Source-only Approved`; final evidence and live
  limitations recorded. No core or test file was changed by this transition.

## File list

- `docs/stories/ONYX-GWS-1.0.0.md` (implementation status, evidence, checklist
  and handoff record updated)
- `core/google_workspace_connector_v1.py` (`sqlite.v3/FileSeal.v2`, required
  generation-anchor and identity-pseudonymizer ports, copy-on-write journaled
  publication/recovery, process locking and sanitized provider failures)
- `tests/test_google_workspace_connector_v1.py` (88 passing focused contracts covering
  exact object-set, preexisting bytes, all sidecars, crash recovery, replay,
  tamper interposition, thread/process concurrency and secret traceback)

## Dev Agent Record

### Agent Model Used

- GPT-5.6 (Vulcan / AEXOS Dev)

### Debug Log References

- Third repair focused validation:
  `.venv-release-v16\Scripts\python.exe -m pytest tests/test_google_workspace_connector_v1.py -q --basetemp "$env:TEMP\onyx-gws-v3-third-final-focused"`
  - Result: **88 passed, 1 platform-conditional skipped, 0 failed**.
- Third repair combined validation:
  `.venv-release-v16\Scripts\python.exe -m pytest tests/test_google_workspace_connector_v1.py tests/test_goal_agent_operations_v1.py tests/test_event_analytics_v1.py -q --basetemp "$env:TEMP\onyx-gws-v3-third-final-combined"`
  - Result: **135 passed, 1 platform-conditional skipped, 0 failed**.
- Third repair static validation:
  `.venv-release-v16\Scripts\python.exe -m ruff check core/google_workspace_connector_v1.py tests/test_google_workspace_connector_v1.py`
  - Result: **All checks passed**.
  `.venv-release-v16\Scripts\python.exe -m py_compile core/google_workspace_connector_v1.py tests/test_google_workspace_connector_v1.py`
  - Result: **passed**.

- Final QA-finding repair focused validation:
  `.venv-release-v16\Scripts\python.exe -m pytest tests/test_google_workspace_connector_v1.py -q --basetemp "$env:TEMP\onyx-gws-v3-qa-final-focused2"`
  - Result: **79 passed, 1 platform-conditional skipped, 0 failed**.
- Final QA-finding repair combined validation:
  `.venv-release-v16\Scripts\python.exe -m pytest tests/test_google_workspace_connector_v1.py tests/test_goal_agent_operations_v1.py tests/test_event_analytics_v1.py -q --basetemp "$env:TEMP\onyx-gws-v3-qa-final-combined2"`
  - Result: **126 passed, 1 platform-conditional skipped, 0 failed**.
- Final QA-finding static validation:
  `.venv-release-v16\Scripts\python.exe -m ruff check core/google_workspace_connector_v1.py tests/test_google_workspace_connector_v1.py`
  - Result: **All checks passed**.
  `.venv-release-v16\Scripts\python.exe -m py_compile core/google_workspace_connector_v1.py tests/test_google_workspace_connector_v1.py`
  - Result: **passed**.

- Fresh independent NO-GO repair focused validation:
  `.venv-release-v16\Scripts\python.exe -m pytest tests/test_google_workspace_connector_v1.py -q --basetemp "$env:TEMP\onyx-gws-v3-final-focused"`
  - Result: **65 passed, 1 platform-conditional skipped, 0 failed**.
- Fresh independent NO-GO repair combined validation:
  `.venv-release-v16\Scripts\python.exe -m pytest tests/test_google_workspace_connector_v1.py tests/test_goal_agent_operations_v1.py tests/test_event_analytics_v1.py -q --basetemp "$env:TEMP\onyx-gws-v3-final-combined"`
  - Result: **112 passed, 1 platform-conditional skipped, 0 failed**.
- Fresh static validation:
  `.venv-release-v16\Scripts\python.exe -m ruff check core/google_workspace_connector_v1.py tests/test_google_workspace_connector_v1.py`
  - Result: **All checks passed**.
  `.venv-release-v16\Scripts\python.exe -m py_compile core/google_workspace_connector_v1.py tests/test_google_workspace_connector_v1.py`
  - Result: **passed**.

- Baseline focused reproduction:
  `.venv-release-v16\\Scripts\\python.exe -m pytest tests/test_google_workspace_connector_v1.py -q --basetemp "$env:TEMP\\onyx-gws-focused-baseline"`
  - Result: **44 passed, 2 failed**.
  - Failure 1: same-key reopen rejected with `durable metadata file container
    authentication failed`.
  - Failure 2: direct row mutation was masked by the same container error.
- Final focused validation:
  `.venv-release-v16\\Scripts\\python.exe -m pytest tests/test_google_workspace_connector_v1.py -q --basetemp "$env:TEMP\\onyx-gws-focused-final"`
  - Result: **54 passed, 0 failed**.
- Final combined validation:
  `.venv-release-v16\\Scripts\\python.exe -m pytest tests/test_google_workspace_connector_v1.py tests/test_goal_agent_operations_v1.py tests/test_event_analytics_v1.py -q --basetemp "$env:TEMP\\onyx-gws-combined-final"`
  - Result: **101 passed, 0 failed**.
- Static validation:
  `.venv-release-v16\\Scripts\\python.exe -m ruff check core/google_workspace_connector_v1.py tests/test_google_workspace_connector_v1.py`
  - Result: **All checks passed**.

### Completion Notes List

- Every injected connector/store boundary now translates failures through a
  common sanitizer which raises only after the caught exception scope ends and
  physically clears `__cause__` and `__context__`. Tests exercise status,
  connect, refresh, revoke, resolver, persister, metadata, pending, anchor,
  pseudonymizer and transport failures with secret-bearing exceptions.
- Regular artifact validation now requires `st_nlink == 1` across
  lstat/open-no-follow/fstat/lstat and stable path/descriptor identity. DB,
  seal, journal, stages and lock hardlinks fail closed without mutation and
  without leaking handles.
- Windows durability no longer claims an unsupported alternate write-through
  primitive. All atomic publication uses MoveFileExW with REPLACE_EXISTING (0x1) and
  WRITE_THROUGH (0x8), after FlushFileBuffers and before exact post-publication
  revalidation. Live activation remains blocked pending independent host proof.

- Final review repair binds semantic reads to authenticated byte snapshots via
  SQLite `deserialize`, verifies head sequence equals FileSeal generation and
  trusted anchor, and rechecks the canonical pair before returning data.
- Recovery now reads and validates the trusted anchor before publishing any
  staged artifact. A journal older than the anchor cannot replace newer
  canonical bytes; anchor read/CAS accepts only exact `None`/non-negative `int`
  and exact `bool`, is sanitized, reread and confirmed before journal removal.
- All DB/seal/journal/stage reads are bounded, descriptor-stable, regular-file
  only and reject links/reparse points. COW stages use exact authenticated
  bytes and are semantically authenticated again before PREPARED.
- Windows durability is no longer a directory-sync no-op: write descriptors
  use `FlushFileBuffers`, and publication uses `MoveFileExW` with
  replace-existing/write-through flags. POSIX retains fsync plus
  parent-directory fsync.
- Added probes for pre-seal tamper, replayed copy, get pair swap, old journal,
  bool/truthy/throwing anchors, plaintext/throwing pseudonymizers, oversized
  recovery stages, generation equality, lock timeout and Windows primitive
  ordering/behavior.

- Replaced the replayable v2 pair with source-only `sqlite.v3/FileSeal.v2`.
  Existing files are authenticated read-only before any DDL; there is no v2
  migration or corruption reseal path.
- Mutations now use same-directory copy-on-write staging, stable descriptor
  reads, authenticated PREPARED journals, durable replace/parent sync,
  post-publication verification and an injected external generation-anchor CAS.
  Any failure after PREPARED is `GoogleWorkspaceV1UnknownOutcome` and is
  recovered or left explicitly reconcilable on the next locked open.
- A required injected HMAC identity capability provides domain-separated
  binding/owner/workspace/account pseudonyms. Platform-canonical path binding
  is an HMAC reference, not a raw path digest.
- Adversarials now cover zero-byte and missing-object immutability, all SQLite
  sidecars, partial publication recovery, tamper interposition, two instances,
  two spawned processes, authenticated replay, Windows handle cleanup and
  formatted traceback secret absence.
- Known boundary: the monotonic generation anchor is an injected source-only
  port with deterministic test implementations. Live activation remains
  blocked until a host-backed non-replayable vault/anchor is independently
  accepted and wired. No insecure fallback exists.

- Root cause: the external file seal represented the initial empty database and
  was not refreshed after a successful `put()` commit, so normal reopen saw a
  valid final SQLite file paired with stale authenticated container metadata.
- Split external validation into authenticated manifest parsing and final
  closed-container byte authentication. This keeps wrong-key rejection early
  while allowing row, head and schema/object-set corruption to reach their
  specific internal authenticated boundaries.
- Every successful mutation now commits, verifies physical metadata, closes
  SQLite, writes the new external seal atomically, and verifies that exact
  final container before returning.
- Added safe translation for unreadable SQLite containers and retained explicit
  connection closure, enabling immediate file cleanup on Windows rejection
  paths.
- No assertions were removed or weakened. Focused coverage increased from 46
  to 54 tests. No activation, host wiring, credentials, package, release or
  installed-runtime surface was changed.
- Independent @qa review and any later @devops pre-PR gate remain pending by
  agent-authority design.
- Story DoD self-assessment: all applicable implementation, security, focused
  testing, combined regression, lint, documentation and file-list items are
  complete. Build/install/live verification is not applicable and is expressly
  outside this source-only story. The only unchecked story items are the
  independent @qa verdict and the conditional @devops pre-PR gate.
