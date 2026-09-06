# Onyx V18 Document Intake - source acceptance

> **SUPERSEDED FOR CURRENT-STATE CLAIMS.** Retained as exact V18.1 source
> evidence. Use [`CURRENT_RELEASE_STATUS.md`](../CURRENT_RELEASE_STATUS.md).

Date: 2026-07-31

Status: accepted as a source-level, default-on-for-new-Windows-bootstrap V18.1
slice over the accepted V17 runtime. No V18.1 package was built or installed
for this record.

## Delivered contract

- `document_intake_read` accepts only the exact metadata fields `alias`,
  `source`, `logical_document_id`, `revision_id`, `filename` and `media_type`.
  It accepts no filesystem path, workspace identity, artifact identifier or
  caller-provided digest.
- The controller resolves an existing workspace alias, reattests the exact
  control-plane artifact index row, reopens the content-addressed bytes through
  `ArtifactService`, verifies SHA-256 and then uses the accepted Phase 7
  Approved Source registry and `GovernedDocumentIngestorV1`.
- Existing revoked, stale, corrupt or binding-drifted source identities are
  denied. Only a genuinely absent source identity can be registered; an
  immutable identity is never resurrected.
- Public output contains redacted requirements, decisions, QA and poison
  signals. Citations expose only the stable alias plus document SHA-256.
  Filesystem paths, raw bytes, internal IDs and secrets are excluded.
- `instructions_authority: false` is host-owned metadata at the public result,
  statement and citation levels. Document text cannot set or overwrite it.
- Cancellation before the first source metadata commit, global kill before
  result publication, close/read races, self-close, controller reopen and rollback
  to V17 are fail-closed and covered by tests.
- The runtime adds no provider, network, subprocess or untrusted/model-owned UI
  path to document intake. It is a bounded local read and analysis adapter
  around the existing V17 engine.

## Host attachment provisioning

- The desktop QFileDialog/drop path is intercepted only when V18 is available.
  The selected path crosses a dedicated host callback and is never inserted in
  a model prompt, log or tool argument. The model receives only the six exact
  public fields required by `document_intake_read`.
- When V18 is unavailable, the legacy file attachment prompt remains unchanged.
  With V18 available, implicit `ui.current_file` materialization is disabled;
  an independent, explicit `file_processor` path remains supported through its
  existing governance path.
- `provision_trusted_attachment` refuses system, installation, control-plane
  and CAS roots, plus symlink, reparse and hardlink sources. It revalidates file
  identity after `ArtifactService.publish_file`, before metadata commit.
- Artifact index insertion is transactional and content-idempotent. The alias
  is deterministic from SHA-256. Once alias registration is invoked, any
  uncertain register/readback outcome retains the exact index row fail-closed
  and raises typed reconciliation-required; a later retry can reattest it.
  Rollback occurs only after a conflicting durable alias authoritatively proves
  that the attempted binding did not commit.
- V18 owns the host attachment callback explicitly. Rollback restores the exact
  predecessor only while the callback is still V18-owned, so legacy dispatch
  returns without leaving a stale callback or overwriting a later owner.
- A normal V18 GUI launch delegates to the accepted V17 single-instance class
  and therefore uses the same stable Windows mutex before live-host imports.
  A second GUI launch exits immediately; preflight and all smoke modes remain
  independent, and the handle is closed on success, refusal and failure paths.
- Unsupported, secret-like or unusable filenames are rejected before CAS
  publication. The complete model-facing projection is validated before the
  artifact index or alias can commit.

## Authority lifecycle hardening

- Artifact capability, pinned directory and Windows trusted-directory closes
  commit `closed` only after lower-level handle closure succeeds.
- Explicit close remains retryable after state, native handle or trusted
  boundary failure. Concurrent closes are serialized and active operations are
  drained before authority retirement.
- A trusted-directory constructor tracks every opened handle. Cleanup attempts
  every tracked handle, retains failures in a fail-closed queue and blocks any
  competing authority construction until cleanup succeeds.
- The host capability finalizer remains armed until both pinned state and the
  trusted boundary confirm closure.
- Residual limitation: a real GC finalizer is one-shot. If pinned-state closure
  itself fails during GC after the capability has already become unreachable,
  the boundary is intentionally not closed out of order. This can retain a
  fail-closed OS handle until process exit; production code must use explicit
  `close()` and its retry path.

## Evidence

- Historical precursor controller E2E gate: `17 passed` with `-W error`, including
  alias -> artifact index -> CAS -> Approved Source -> governed ingestor,
  tamper, cross-workspace drift, revoke, stale, cancel, kill, close race and
  controller close/reopen.
- Historical precursor V18 controller, activation, bootstrap and package-definition gate:
  `47 passed` with `-W error`.
- Historical precursor consolidated Artifact Service, Windows close stack, controller, activation,
  bootstrap and package-definition gate: `191 passed, 8 skipped, 25 subtests
  passed` with `-W error`.
- Post-review V18.1 focused host attachment/UI/smoke/mutex gate:
  `71 passed in 34.49s`:

  ```powershell
  .\.venv\Scripts\python.exe -m pytest -q tests\test_document_intake_live_v1.py tests\test_document_intake_ui_v181.py tests\test_onyx_live_activation_v18.py tests\test_package_hygiene_v1.py -W error
  ```

- Final consolidated regression, including the Phase 11 transient-busy startup
  degradation that prevents `cleanup_root_handle_busy` from crashing Onyx:
  `260 passed, 9 skipped, 36 subtests passed in 89.77s`:

  ```powershell
  .venv\Scripts\python.exe -m pytest -q -W error tests\test_artifact_service.py tests\test_phase11_windows_clone_cleanup_v1.py tests\test_phase11_windows_namespace_v1.py tests\test_phase11_live_mission_v1.py tests\test_document_intake_live_v1.py tests\test_document_intake_ui_v181.py tests\test_onyx_live_activation_v18.py tests\test_package_hygiene_v1.py tests\test_packaging_paths.py
  ```

- Full Ruff passed for the V18.1 core, activation, bootstrap, package and test
  files. Compile-critical Ruff (`E9,F63,F7,F82`) passed for the existing
  `main.py` and `ui.py` hosts. Changed-file `py_compile` passed.
- Scoped `git diff --check` passed for V18.1 core/scripts/tests/docs. The host
  files retain pre-existing whole-file CRLF churn and style debt, so neither a
  whole-host Ruff claim nor whitespace normalization is made here.
- Runtime-document discovery selected this acceptance record (`148` documents).
- Stable source bootstrap `--document-intake-smoke-test`: exit `0`; first and
  controller-reopened ingestion completed with four citations each; network,
  provider, child-process and trusted-UI prompt counters were all zero. This is
  an in-process controller reopen, not a two-process restart claim.
- After the successful Windows smoke process exited, Qt emitted the pre-existing
  non-fatal `Win32 exception occurred releasing IUnknown` teardown diagnostic.
  Exit status and result assertions remained successful; this is tracked as a
  host teardown diagnostic, not silently counted as a V18.1 functional pass.
- The official build script now requires the same frozen V18.1 smoke after the
  existing package preflight, Governance smoke and Founder smoke. That package
  gate is coded and source-tested but was not executed against a new bundle in
  this acceptance step.

## Limits before release promotion

- No V18.1 frozen bundle, installer, portable archive or installed-host smoke
  was produced in this acceptance step.
- No live Gemini, microphone, speaker, external connector or network workflow
  was exercised by this provider-free gate.
- macOS and Linux host-native behavior remains unverified. The V18 bootstrap
  deliberately falls back to V17 outside Windows.
- Existing Windows V17 release artifacts remain the last built and installed
  binaries until a separately authorized V18 build/install run completes.
