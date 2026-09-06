# ONYX-REL-1.1.9-P0-LAZY-EXTERNAL-AGENT-STARTUP - Provider-Free Boot

## Status

**In Progress**

## Story

**As the** Onyx release owner,  
**I want** optional external coding-agent discovery to occur only when its
explicit mission surface is used,  
**so that** normal startup remains provider-free, fast, deterministic and free
of child processes without removing the external-agent capability.

## Acceptance Criteria

1. The failed V35 candidate and its source-freeze manifest remain immutable.
2. Phase 11 construction validates and stores the external-agent factory but
   does not invoke it, inspect an ambient provider or start a child process.
3. The first explicit external-agent create, recovery validation, execution or
   owner-confirmed quarantine cleanup discovers the provider exactly once and
   reuses the exact adapter.
4. Disabled, unavailable and invalid providers fail closed with a bounded
   reason; unexpected factory defects are not silently downgraded.
5. Shutdown never instantiates an unused provider and closes an instantiated
   provider exactly through the existing lifecycle.
6. Phase 11, V15 and native startup regressions pass with warnings as errors.
7. Release V36 authenticates the changed runtime and tests over immutable V35.
8. The V36 source candidate remains immutable failed evidence; its authenticated
   V24 guard false-negative is corrected only in V37, whose frozen Windows
   build remains immutable failed evidence. The V37 launcher-chain evidence
   defect is corrected only in V38. Pre-freeze Phase 11 validation then exposed
   the Win32 legacy `MAX_PATH` boundary in clone-budget enumeration; V39 binds
   that correction and must pass all packaged smoke gates before installation
   is attempted.

## Tasks / Subtasks

- [x] Preserve and diagnose the failed V35 native startup evidence.
- [x] Implement thread-safe, on-demand external-agent discovery.
- [x] Add regression proving zero factory calls at construction and one call on
  first explicit use.
- [x] Preserve constructor rollback coverage through a post-authority
  Project Autopilot failure seam.
- [x] Run focused Phase 11/V15/native regressions.
- [x] Run the complete portable release gate.
- [x] Generate and verify Release V36.
- [x] Freeze V36 and prove lazy discovery passes the packaged startup boundary.
- [x] Diagnose the next V36 failure as an obsolete exact-class smoke assertion,
  not a host construction or V24 authority failure.
- [x] Authenticate the controller-owned V24 guard without accepting arbitrary
  subclasses, altered descriptors or duplicate bindings.
- [x] Add adversarial guard tests and run the real source startup smoke.
- [x] Generate and independently verify Release V37 over immutable V36.
- [x] Freeze V37 and run its isolated Windows build through the next gate.
- [x] Diagnose the V37 failure as missing V24 entry evidence, not failed V24
  traversal or failed native host construction.
- [x] Persist and close the V24 entry marker before terminal delegation, without
  adding a false post-return success marker or weakening the release gate.
- [x] Regenerate the packaged HUD contract and independently verify Release V38
  over immutable V37.
- [x] Reproduce the Phase 11 failure at a 261-character Git pack path and prove
  that the file exists while legacy `Path.lstat()` reports `WinError 3`.
- [x] Use Win32 extended-length paths for the complete bounded clone walk,
  retry complete enumeration after transient replacement and fail closed when
  the tree does not stabilize.
- [x] Add regression coverage for transient replacement, persistent churn and
  a real path beyond the legacy Windows limit.
- [x] Run the complete Project Autopilot and V15 executable integration suites.
- [x] Generate and independently verify Release V39 over immutable V38.
- [ ] Freeze and build the isolated V39 Windows candidate.

## Failure Evidence

- Source freeze: `Onyx-V35-Windows-Candidate-20260810.SOURCE_FREEZE.json`
- Frozen root: `2f192a7a8a7945082803ca22aedea12574e0c7f45168aa89cdec501b0274795c`
- Build reached `Packaged native startup smoke (Windows, baseline)` and exited
  `70`.
- Trace: `main.OnyxLive.__init__` to `Phase11LiveMissionV1.__init__` to the V15
  external-agent factory to `discover_claude_code_provider_v1()` to
  `claude --version`.
- Contract failure: `NativeStartupSmokeError: native startup attempted a child
  process`.
- V36 source freeze:
  `Onyx-V36-Windows-Candidate-20260810.SOURCE_FREEZE.json`.
- V36 frozen root:
  `3447b37ad3d1bcfbd728a1caf6b2c52c429ce015218f6e20c8c2b28ca091d99e`.
- V36 passed the fallback and V24 preflight stages and crossed the former
  `claude --version` boundary with no subprocess. It then exited `70` because
  `native_startup_smoke_v1.py` required
  `type(instance) is imported_main.OnyxLive`, while V24 intentionally and
  securely returns its exact per-instance `OnyxLiveV24Guard_*` subclass.
- V37 source freeze:
  `Onyx-V37-Windows-Candidate-20260810.SOURCE_FREEZE.json`.
- V37 frozen root:
  `52718d33cb3bc38ac9c4da2d3aafcf436ecdb62eb673b18334a65ffa073e76b9`.
- V37 passed fallback preflight, V24 preflight and the packaged native startup
  host contract. The build then stopped because
  `launch_onyx_live_v24.pyw` delegated the diagnostic without first writing the
  V24 entry marker required by `build_release.py`; that evidence was therefore
  impossible for an otherwise successful traversal to produce.
- V38 was superseded before source freeze. In the wider Phase 11 gate,
  `_bounded_tree_usage()` enumerated a real clone pack path of 261 characters;
  the file remained present, but an unprefixed Win32 `lstat` failed with
  `WinError 3`. The V39 implementation converts only the local measurement
  root to the Win32 extended-length namespace, retains reparse/link rejection,
  restarts the entire measurement after a transient missing entry, and returns
  `controlled_clone_tree_unstable` after bounded retries instead of accepting
  a partial quota.

## Dev Agent Record

### Agent Model Used

Codex

### Debug Log References

- Focused lint: passed.
- Focused lazy/startup tests: 6 passed.
- Native startup contract tests: 3 passed.
- Integrated Phase 11/V15/native suite: 124 passed, 1 platform skip, 11
  subtests passed.
- Portable/POSIX source suite: 117 passed, 53 native-host skips.
- Release V34-V36, HUD package and Phase V41 selection: 18 passed.
- Release V36 fixture SHA-256:
  `1a9e63b28c251dcd505c3a5804316c1d6297e568c7dc53de622126eaa7a1b236`.
- Release V36 authenticated root:
  `a9ebbf21df121bcec09dec7bf713cac8010830e1d534b0ab8c4ea22e5d57e4c7`.
- V36 source-freeze verification after the failed build: 2,623 files;
  139,655,384 bytes; root unchanged.
- V37 V24 guard smoke tests: 34 passed, 2 POSIX-only skips.
- Real Windows source smoke: V24 host constructed, real UI visible, cinematic
  renderer active, callbacks bound, zero network/provider/process calls.
- Release/HUD regression: 74 passed, 2 POSIX-only skips.
- Release V37 fixture SHA-256:
  `ebe6eff3d8c00eaeafa657fe99287434181de5fc7c0521be1f05d7906fb93cf5`.
- Release V37 authenticated root:
  `31374474b7f76502ba3a833fc7efa62247f57df08fe407e91cc13f1548f03aeb`.
- V38 launcher/HUD/release regression: 128 passed, 2 POSIX-only skips.
- Release V38 fixture SHA-256:
  `9aae7dc4c4adee5c8a3d32b652f549bc7c2a4871dd70dfccf22b9446ac1aec1a`.
- Release V38 authenticated root:
  `8ea23b9e608a9a3aa2833c88073505ae5908a3053006455d997a36a5aef60962`.
- Packaged HUD manifest SHA-256:
  `a8684204246303f8302451a0b5bb2218e843d37acefa54a7be41f8a5c875cc2b`.
- Phase 11 clone-tree contract: 3 passed (transient replacement, persistent
  instability fail-closed and real Win32 path beyond 260 characters).
- Phase 11 V15 executable integration: 12 passed.
- Complete Project Autopilot suite: 55 passed, 34 subtests passed.
- Release V32-V39 genealogy plus V24 launcher: 33 passed.
- Release V39 fixture SHA-256:
  `f08504b3148394d7e6bf18128b0105149675434f0d1bbfa24ada67ca8f6b9876`.
- Release V39 authenticated root:
  `2ea6b96d612db8e3519db6b1ff7a2538deef1d2b876f896cb86d658ac4b05e9e`.

### Completion Notes List

External coding-agent authority and behavior are preserved. Discovery is now an
explicit-operation cost instead of a boot-time side effect. Build and installed
runtime evidence remain pending.

### File List

- `core/phase11_live_mission_v1.py`
- `tests/test_phase11_external_agent_v1.py`
- `tests/test_phase11_live_mission_v1.py`
- `scripts/generate_release_workflow_v36.py`
- `scripts/verify_release_workflow_v36.py`
- `scripts/verify_phase5_exit_retirement_v1.py`
- `tests/fixtures/release_workflow_transition_v36.json`
- `tests/test_release_workflow_transition_v34.py`
- `tests/test_release_workflow_transition_v35.py`
- `tests/test_release_workflow_transition_v36.py`
- `docs/onyx/checkpoints/RELEASE_WORKFLOW_V36_VERIFIER_RECEIPT.json`
- `core/native_startup_smoke_v1.py`
- `docs/onyx/acceptance/VE-HUD-CURRENT-V26-E6-001.manifest.json`
- `scripts/generate_release_workflow_v37.py`
- `scripts/verify_release_workflow_v37.py`
- `tests/fixtures/release_workflow_transition_v37.json`
- `tests/test_native_startup_smoke_v1.py`
- `tests/test_release_workflow_transition_v32.py`
- `tests/test_release_workflow_transition_v33.py`
- `tests/test_release_workflow_transition_v37.py`
- `docs/onyx/checkpoints/RELEASE_WORKFLOW_V37_VERIFIER_RECEIPT.json`
- `scripts/launch_onyx_live_v24.pyw`
- `tests/test_launch_onyx_live_v24.py`
- `core/onyx_packaged_runtime_hud_contract_v1.manifest.json`
- `core/onyx_packaged_runtime_hud_contract_v1.py`
- `scripts/generate_hud_v26_manifests.py`
- `scripts/generate_release_workflow_v38.py`
- `scripts/verify_release_workflow_v38.py`
- `tests/fixtures/release_workflow_transition_v38.json`
- `tests/test_release_workflow_transition_v38.py`
- `docs/onyx/checkpoints/RELEASE_WORKFLOW_V38_VERIFIER_RECEIPT.json`
- `core/phase11_project_autopilot_v1.py`
- `tests/test_phase11_project_autopilot_v1.py`
- `scripts/generate_release_workflow_v39.py`
- `scripts/verify_release_workflow_v39.py`
- `tests/fixtures/release_workflow_transition_v39.json`
- `tests/test_release_workflow_transition_v39.py`
- `docs/onyx/checkpoints/RELEASE_WORKFLOW_V39_VERIFIER_RECEIPT.json`
- `docs/stories/ONYX-REL-1.1.9-P0-LAZY-EXTERNAL-AGENT-STARTUP.md`

## QA Results

Pending candidate-bound review.
