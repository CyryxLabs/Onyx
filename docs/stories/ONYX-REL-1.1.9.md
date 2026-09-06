# ONYX-REL-1.1.9 - Cross-platform successor release candidate

## Status

**V53 R15B source frozen and independently portable-validated; the bounded
Linux container build/package/clean-install preflight, live DayOps and Gemini
native-audio provider gates passed; formal/public release remains NO-GO.** The
first parallel R15B Windows build produced Setup and portable bytes
but failed closed when its isolated Setup smoke correctly detected the still-live
R10B predecessor. A recovery watcher now preserves the R10B eight-hour soak,
then performs authenticated shutdown, archives the rejected attempt, rebuilds
the same manifest-bound R15B source and rearms every downstream acceptance gate.
Native Linux GUI/audio, native macOS, trusted signing/notarization,
all-platform clean-host lifecycle, legal approval, final cross-platform SBOM
reconciliation and independent review remain open.

## Requirement source

- Owner goal: prepare the post-macOS/POSIX/mode-fix source as Onyx 1.1.9
  without changing runtime semantics.
- Preserve the installed Windows 1.1.8 acceptance and every 1.1.8 artifact,
  document and evidence record as predecessor history.
- Extend the authenticated Phase 5 current-successor chain; never rebind or
  weaken historical hashes.

## Acceptance criteria

- [x] Every active product, packaging, workflow and operator-command version
  surface defaults to 1.1.9.
- [x] Exact 1.1.8 evidence and artifacts remain present and unmodified.
- [x] Current status distinguishes the installed Windows 1.1.8 predecessor,
  its in-progress soak, and the unqualified cross-platform 1.1.9 candidate.
- [x] V11 authenticated successor transition preserves V10, V9 and every earlier
  record as immutable predecessors and binds the current local source.
- [ ] Independent review accepts hermetic diagnostic namespaces, including the
  Phase 11 boundary, without sharing production state.
- [x] The local V11 tree passes authenticated successor/retirement, mission,
  Phase 6 and frozen-package gates and produced the installed Windows
  candidate.
- [ ] An external zero-divergence seal independently binds the final V11 tree
  and artifact hashes.
- [ ] Independent review confirms that the correction changes diagnostic
  isolation only and does not widen engine, voice, authority or HUD semantics.

## File list

- `core/version.py`
- `packaging/onyx.spec`
- `scripts/generate_icons.py`
- `scripts/run_linux_release_validation.sh`
- `.github/workflows/release-packages.yml`
- `docs/INSTALLATION.md`
- `readme.md`
- `docs/onyx/CURRENT_RELEASE_STATUS.md`
- `docs/onyx/DOCUMENTATION_INDEX.md`
- `docs/onyx/FINAL_EVIDENCE_INDEX_1.1.9.md`
- `docs/onyx/DOCUMENT_SUPERSESSION_REGISTRY_R8B_2026-08-11.md`
- `docs/onyx/DOCUMENT_SUPERSESSION_REGISTRY_R10B_2026-08-11.md`
- `docs/onyx/DOCUMENT_SUPERSESSION_REGISTRY_R15B_2026-08-11.md`
- `docs/onyx/IMPLEMENTATION_ROADMAP.md`
- `docs/onyx/ONYX_PROJECT_COMPLETION_ROADMAP_2026-08-01.md`
- `scripts/verify_current_release_docs_r15b.py`
- `tests/test_verify_current_release_docs_r15b.py`
- `docs/onyx/ONYX_PROJECT_COMPLETION_ROADMAP_2026-08-04.md`
- `docs/onyx/ONYX_PROJECT_COMPLETION_ROADMAP_V23_2026-08-04.md`
- `docs/onyx/ONYX_PROJECT_COMPLETION_ROADMAP_V24_2026-08-04.md`
- `docs/onyx/operations/ONYX_1_1_9_V31_WINDOWS_ACCEPTANCE_2026-08-04.md`
- `docs/onyx/operations/ONYX_1_1_9_V41_WINDOWS_ACCEPTANCE_2026-08-10.md`
- `docs/onyx/operations/ONYX_1_1_9_V41_SBOM_RECONCILIATION_2026-08-10.md`
- `docs/onyx/operations/ONYX_1_1_9_V41_LINUX_BUILD_FAILURE_2026-08-10.md`
- `docs/onyx/FINAL_EVIDENCE_REVIEW_PROTOCOL.md`
- `docs/onyx/LEGAL_RELEASE_APPROVAL_1.1.9.md`
- `docs/onyx/THIRD_PARTY_LICENSE_REVIEW_WORKLIST_1.1.9.md`
- `docs/onyx/checkpoints/LEGAL_DECISION_PACKET_R10B_V1.json`
- `docs/onyx/checkpoints/PHASE5_CURRENT_SUCCESSOR_TRANSITION_V10.md`
- `tests/fixtures/phase5_current_successor_transition_v10.json`
- `docs/onyx/checkpoints/PHASE5_CURRENT_SUCCESSOR_TRANSITION_V11.md`
- `tests/fixtures/phase5_current_successor_transition_v11.json`
- `docs/onyx/checkpoints/PHASE5_CURRENT_SUCCESSOR_TRANSITION_V9.md`
  (immutable superseded predecessor)
- `tests/fixtures/phase5_current_successor_transition_v9.json`
  (immutable superseded predecessor)
- `scripts/verify_phase5_exit_retirement_v1.py`
- `tests/test_phase5_current_successor_transition_v2.py`
- `tests/test_phase5_current_successor_transition_v10.py`
- `tests/test_phase5_current_successor_transition_v11.py`
- `tests/test_release_preparation_v110.py`
- `tests/test_release_version_v119.py`
- `tests/test_documentation_precedence_v1.py`
- `core/missions.py`
- `core/onyx_hud_current_acceptance_v28.py`
- `core/onyx_hud_current_acceptance_v29.py`
- `core/onyx_packaged_runtime_hud_contract_v1.py`
- `core/onyx_packaged_runtime_hud_contract_v1.manifest.json`
- `docs/onyx/acceptance/VE-HUD-CURRENT-V28-E6-001.manifest.json`
- `docs/onyx/acceptance/VE-HUD-CURRENT-V29-E6-001.manifest.json`
- `docs/onyx/checkpoints/RELEASE_WORKFLOW_V42_VERIFIER_RECEIPT.json`
- `../Onyx-Release-Orchestration/verify-owner-name-r15b.py`
- `../Onyx-Release-Orchestration/verify-orb-installed-r15b.py`
- `../Onyx-Release-Orchestration/wait-build-then-install-r11b.ps1`
- `../Onyx-Release-Orchestration/consolidate-r15b-acceptance.py`
- `../Onyx-Release-Orchestration/test-consolidate-r15b-acceptance.py`
- `../Onyx-Release-Orchestration/wait-r15b-then-consolidate.ps1`
- `../Onyx-Release-Orchestration/capture-live-orb-r15b.py`
- `../Onyx-Release-Orchestration/test_capture_live_orb_r15b.py`
- `../Onyx-Release-Orchestration/wait-r15b-live-then-capture.ps1`
- `../Onyx-Release-Orchestration/generate-r15b-evidence-index.py`
- `../Onyx-Release-Orchestration/test_generate_r15b_evidence_index.py`
- `../Onyx-Release-Orchestration/verify-relocated-source-copy-r15b.py`
- `../Onyx-Release-Orchestration/test_verify_relocated_source_copy_r15b.py`
- `../Onyx-Release-Orchestration/wait-r15b-build-then-verify-inputs.ps1`
- `../Onyx-Release-Orchestration/recover-r15b-build-after-r10b-soak.ps1`
- `../Onyx-Release-Orchestration/verify_r15b_recovery_preflight.py`
- `../Onyx-Release-Orchestration/test_verify_r15b_recovery_preflight.py`
- `../Onyx-Release-Orchestration/r15b-build-recovery/ONYX_1_1_9_R15B_RECOVERY_PREFLIGHT.json`
- `../Onyx-Release-Orchestration/r15b-documentation/ONYX_1_1_9_R15B_RECOVERY_PREFLIGHT_DOCUMENTATION_VERIFICATION.json`
- `../Onyx-Release-Orchestration/wait-r11b-soak-then-linux-container-gate.ps1`
- `../Onyx-Release-Orchestration/offline_license_cache_r15b.py`
- `../Onyx-Release-Orchestration/test_offline_license_cache_r15b.py`
- `../Onyx-Release-Orchestration/r15b-offline-license-cache-v2/manifest.json`
- `../Onyx-Release-Orchestration/r15b-failed-workspaces/linux-preflight-offline-license-gap-20260811T181500/`
- `../Onyx-Release-Orchestration/r15b-failed-workspaces/linux-preflight-primp-offline-gap-20260811T182500/`
- `../Onyx-Release-Orchestration/Dockerfile.release-validation-r15b-v4`
- `../Onyx-Release-Orchestration/verify_release_validation_image_r15b.py`
- `../Onyx-Release-Orchestration/test_verify_release_validation_image_r15b.py`
- `../Onyx-Release-Orchestration/r15b-validation-image-v4/ONYX_1_1_9_R15B_VALIDATION_IMAGE_V4_RECEIPT.json`
- `../Onyx-Release-Orchestration/verify_bundle_inventory_lock_r15b.py`
- `../Onyx-Release-Orchestration/test_verify_bundle_inventory_lock_r15b.py`
- `../Onyx-Release-Orchestration/verify_deb_clean_install_r15b.sh`
- `../Onyx-Release-Orchestration/resume-r15b-linux-clean-gate.ps1`
- `../Onyx-Release-Orchestration/verify_linux_container_gate_r15b.py`
- `../Onyx-Release-Orchestration/test_verify_linux_container_gate_r15b.py`
- `../Onyx-Release-Orchestration/r15b-failed-workspaces/linux-preflight-sbom-lock-gap-20260811T194549/`
- `../Onyx-Release-Orchestration/r15b-failed-workspaces/linux-preflight-clean-home-contract-gap-20260811T205331/`
- `../Onyx-Release-Orchestration/r15b-failed-workspaces/linux-preflight-runner-timeout-20260811T210344/`
- `../Onyx-Release-Orchestration/r15b-failed-workspaces/linux-preflight-relocated-postbuild-ntfs-gap-20260811T210427/`
- `../Onyx-Release-Orchestration/r15b-linux-preflight/ONYX_1_1_9_R15B_LINUX_CONTAINER_GATE_RECEIPT.json`
- `../Onyx-Release-Orchestration/r15b-linux-preflight/ONYX_1_1_9_R15B_LINUX_CONTAINER_GATE_INDEPENDENT_VERIFICATION.json`
- `../Onyx-Release-Orchestration/r15b-linux-preflight/state.json`
- `../Onyx-Release-Orchestration/r15b-documentation/ONYX_1_1_9_R15B_DOCUMENTATION_VERIFICATION.json`
- `../Onyx-Release-Orchestration/r15b-documentation/ONYX_1_1_9_R15B_POST_LINUX_DOCUMENTATION_VERIFICATION.json`
- `../Onyx-Release-Orchestration/r15b-documentation/ONYX_1_1_9_R15B_POST_LINUX_INDEPENDENT_DOCUMENTATION_VERIFICATION.json`
- `../Onyx-Release-Orchestration/r15b-build-recovery/ONYX_1_1_9_R15B_FAILED_BUILD_INPUT_PRESERVATION.json`
- `../Onyx-Release-Orchestration/ONYX_1_1_9_R15B_SOURCE_FREEZE_DRIFT_INCIDENT.json`
- `../Onyx-Release-Orchestration/ONYX_1_1_9_R10B_LONG_SESSION_ATTEMPT4_LAUNCH.json`
- `docs/onyx/checkpoints/RELEASE_WORKFLOW_V45_VERIFIER_RECEIPT.json`
- `docs/onyx/checkpoints/phase5-approval-inbox-v9/mutable-projections/0fc6da87140a3f5455eab5995ab5736edf998fd63f98d860359da850efe61724.snapshot`
- `docs/onyx/operations/ONYX_1_1_9_V41_LINUX_BUILD_FAILURE_2026-08-10.md`
- `docs/onyx/operations/ONYX_1_1_9_V44_SOURCE_FREEZE_2026-08-10.md`
- `scripts/build_release.py`
- `scripts/freeze_release_source.py`
- `scripts/generate_hud_v28_manifests.py`
- `scripts/generate_hud_v29_manifests.py`
- `scripts/generate_r11_historical_blob_pack_v1.py`
- `scripts/generate_phase5_current_successor_transition_v44.py`
- `scripts/generate_phase5_current_successor_transition_v45.py`
- `scripts/generate_release_workflow_v42.py`
- `scripts/generate_release_workflow_v43.py`
- `scripts/generate_release_workflow_v44.py`
- `scripts/generate_release_workflow_v45.py`
- `scripts/monitor_windows_long_session.py`
- `scripts/package_hygiene.py`
- `scripts/verify_release_workflow_v42.py`
- `scripts/verify_release_workflow_v43.py`
- `scripts/verify_release_workflow_v44.py`
- `scripts/verify_release_workflow_v45.py`
- `scripts/verify_r11_projection_retirement_v1.py`
- `tests/fixtures/r11_historical_blob_pack_v1.json`
- `tests/fixtures/r11_historical_blobs_v1.zip`
- `tests/fixtures/phase5_current_successor_transition_v44.json`
- `tests/fixtures/phase5_current_successor_transition_v45.json`
- `tests/fixtures/release_workflow_transition_v42.json`
- `tests/fixtures/release_workflow_transition_v43.json`
- `tests/fixtures/release_workflow_transition_v44.json`
- `tests/fixtures/release_workflow_transition_v45.json`
- `tests/test_hud_source_frozen_selection_v1.py`
- `tests/test_missions.py`
- `tests/test_monitor_windows_long_session.py`
- `tests/test_native_release_gate_v1.py`
- `tests/test_onyx_hud_current_acceptance_v28.py`
- `tests/test_onyx_hud_current_acceptance_v29.py`
- `tests/test_packaged_runtime_hud_contract_v1.py`
- `tests/test_phase5_current_successor_transition_v43.py`
- `tests/test_phase5_current_successor_transition_v44.py`
- `tests/test_phase5_current_successor_transition_v45.py`
- `tests/test_portable_current_release_gate_v1.py`
- `tests/test_release_workflow_transition_v42.py`
- `tests/test_release_workflow_transition_v43.py`
- `tests/test_release_workflow_transition_v44.py`
- `tests/test_release_workflow_transition_v45.py`
- `tests/test_r11_projection_retirement_v1.py`
- `tests/test_close_to_background_v1.py`
- `tests/test_package_hygiene_v1.py`
- `qml/OnyxLiveShellV7.qml`
- `qml/components/OnyxOrbEntityV7.qml`
- `ui.py`
- `qml/OnyxLiveShellGuardedV1.qml`
- `qml/OnyxLiveShellV11.qml`
- `qml/components/OnyxOrbEntityV8.qml`
- `core/onyx_hud_orb_v11.py`
- `core/onyx_hud_current_acceptance_v30.py`
- `docs/onyx/acceptance/VE-HUD-CURRENT-V30-E6-001.manifest.json`
- `core/onyx_live_activation_google_workspace_v1.py`
- `scripts/bootstrap_onyx_live_google_workspace_v1.pyw`
- `scripts/launch_onyx_live_google_workspace_v1.pyw`
- `docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V8.json`
- `docs/onyx/checkpoints/CURRENT_RUFF_SECURITY_EXCEPTIONS_V1.json`
- `docs/onyx/checkpoints/RELEASE_WORKFLOW_V46_VERIFIER_RECEIPT.json`
- `scripts/generate_hud_v30_manifests.py`
- `scripts/generate_phase5_current_successor_transition_v46.py`
- `scripts/generate_release_workflow_v46.py`
- `scripts/verify_release_workflow_v46.py`
- `tests/fixtures/phase5_current_successor_transition_v46.json`
- `tests/fixtures/release_workflow_transition_v46.json`
- `tests/test_current_release_documentation_v46.py`
- `tests/test_onyx_hud_current_acceptance_v30.py`
- `tests/test_phase5_current_successor_transition_v46.py`
- `tests/test_release_workflow_transition_v46.py`
- `requirements.txt`
- `requirements-dev.txt`
- `requirements.lock`
- `docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V9.json`
- `docs/onyx/checkpoints/RELEASE_WORKFLOW_V47_VERIFIER_RECEIPT.json`
- `scripts/generate_phase5_current_successor_transition_v47.py`
- `scripts/generate_release_workflow_v47.py`
- `scripts/verify_current_successor_retirement_v1.py`
- `scripts/verify_phase5_exit_retirement_v1.py`
- `scripts/verify_release_workflow_v47.py`
- `tests/fixtures/phase5_current_successor_transition_v47.json`
- `tests/fixtures/release_workflow_transition_v47.json`
- `tests/test_current_release_documentation_v47.py`
- `tests/test_current_successor_retirement_v9.py`
- `tests/test_freeze_release_source_v47.py`
- `tests/test_phase5_current_successor_transition_v47.py`
- `tests/test_release_workflow_transition_v47.py`
- `docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V10.json`
- `docs/onyx/checkpoints/RELEASE_WORKFLOW_V48_VERIFIER_RECEIPT.json`
- `scripts/generate_phase5_current_successor_transition_v48.py`
- `scripts/generate_release_workflow_v48.py`
- `scripts/verify_release_workflow_v48.py`
- `tests/fixtures/phase5_current_successor_transition_v48.json`
- `tests/fixtures/phase5_exit_retirement_v2.json`
- `tests/fixtures/release_workflow_transition_v48.json`
- `tests/test_current_successor_retirement_v10.py`
- `tests/test_freeze_release_source_v48.py`
- `tests/test_phase5_current_successor_transition_v48.py`
- `tests/test_release_workflow_transition_v48.py`
- `scripts/reconcile_release_compliance_v1.py`
- `scripts/verify_legal_decision_packet_r10b_v1.py`
- `tests/test_release_compliance_reconciliation_v1.py`
- `tests/test_legal_decision_packet_r10b_v1.py`
- `tests/test_current_release_documentation_r10b.py`
- `scripts/generate_release_workflow_v50.py`
- `scripts/generate_phase5_current_successor_transition_v50.py`
- `scripts/verify_release_workflow_v50.py`
- `tests/fixtures/phase5_current_successor_transition_v50.json`
- `tests/test_phase5_current_successor_transition_v50.py`
- `tests/fixtures/release_workflow_transition_v50.json`
- `tests/test_release_workflow_transition_v50.py`
- `docs/onyx/checkpoints/RELEASE_WORKFLOW_V50_VERIFIER_RECEIPT.json`
- `.github/workflows/release-qualification.yml`
- `docs/onyx/FINAL_EVIDENCE_REVIEW_PROTOCOL.md`
- `docs/onyx/FORMAL_RELEASE_CONTRACT.md`
- `docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V11.json`
- `docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V12.json`
- `docs/onyx/checkpoints/RELEASE_WORKFLOW_V51_VERIFIER_RECEIPT.json`
- `scripts/generate_final_qualification_provenance_v1.py`
- `scripts/generate_phase5_current_successor_transition_v51.py`
- `scripts/generate_release_workflow_v51.py`
- `scripts/prepare_qualification_artifacts_v1.py`
- `scripts/verify_final_release_qualification_v1.py`
- `scripts/verify_release_workflow_v51.py`
- `scripts/verify_source_freeze_v1.py`
- `tests/fixtures/phase5_current_successor_transition_v51.json`
- `tests/fixtures/release_workflow_transition_v51.json`
- `tests/test_current_successor_retirement_v11.py`
- `tests/test_current_successor_retirement_v12.py`
- `tests/test_final_release_qualification_v1.py`
- `tests/test_formal_release_contract_v1.py`
- `tests/test_freeze_release_source_v51.py`
- `tests/test_phase5_current_successor_transition_v51.py`
- `tests/test_release_qualification_artifacts_v1.py`
- `tests/test_release_workflow_transition_v51.py`
- `tests/test_verify_source_freeze_v1.py`
- `scripts/monitor_windows_long_session.py`
- `tests/test_monitor_windows_long_session.py`
- `C:/MAAX_Assistant/Onyx-V46-Windows-Candidate-R8B-20260810/acceptance/installed-v46-r8b/ONYX_1_1_9_V46_WINDOWS_INSTALLED_ACCEPTANCE_RECEIPT.json`
  (candidate-bound evidence outside the source tree)
- `C:/MAAX_Assistant/Onyx-V46-Windows-Candidate-R8B-20260810/acceptance/installed-v46-r8b/generate_windows_candidate_sbom_v46.py`
  (candidate-bound evidence harness outside the source tree)
- `C:/MAAX_Assistant/Onyx-V46-Windows-Candidate-R8B-20260810/acceptance/installed-v46-r8b/sbom-windows-r8b/SBOM.spdx.json`
  (unsigned Windows technical inventory outside the source tree)
- `C:/MAAX_Assistant/Onyx-V49-Source-Candidate-R10B-20260811.SOURCE_FREEZE.json`
  (immutable R10B source-freeze evidence outside the source tree)
- `C:/MAAX_Assistant/Onyx-V49-Windows-Candidate-R10B-20260811/acceptance/installed-r10b/ONYX_1_1_9_R10B_INSTALLED_ACCEPTANCE_RECEIPT.json`
  (candidate-bound installed evidence outside the source tree)
- `C:/MAAX_Assistant/Onyx-V49-Windows-Candidate-R10B-20260811/acceptance/installed-r10b/ONYX_1_1_9_R10B_COMPLIANCE_RECONCILIATION.json`
  (candidate-bound technical compliance evidence outside the source tree)

## Evidence boundary

This story now includes a locally installed Windows R10B candidate. That does
not establish signing/notarization, clean-host lifecycle, terminal long-session
acceptance, native Linux/macOS qualification, legal approval, independent
review or public-release readiness.

## Dev Agent Record

- 2026-08-10: reproduced the V41 exhausted-retry defect and corrected the
  mission authority ordering in successor source.
- 2026-08-10: traced the V41 Linux exit-70 failure to package-harness selection;
  explicitly selected the non-portable POSIX baseline without changing the
  production frozen default or native-startup boundary.
- 2026-08-10: authenticated HUD V28, Phase 5 V44 and release workflow V42.
- 2026-08-10: corrected the successor long-session health probe so Onyx's
  intended hidden resident state remains valid while any hung or absent
  top-level window still fails closed.
- 2026-08-10: V42 and V43 source freezes exposed successive non-hermetic pytest
  dependencies on `.git` plus an omitted `plans/` projection. V44 replaces
  them with an authenticated deterministic 49-blob/26-HEAD-edge historical
  pack and preserves both failed freezes as diagnostic evidence.
- 2026-08-10: focused integrated release/HUD/workflow/monitor/documentation/
  historical-retirement/mission validation passed 211 tests in 146.85 seconds using an isolated
  pytest base directory.
- 2026-08-10: exact V44 source freeze passed the same 211-test scope in 114.49
  seconds without a Git object database.
- 2026-08-10: advanced the authenticated HUD, Phase 5 and release authorities
  to V29/V45, preserving V44 and earlier records as immutable predecessors.
- 2026-08-10: repaired successor-only test routing and added the exact historical
  Linux desktop projection required to reproduce the R11 evidence pack without
  weakening current runtime or installer gates.
- 2026-08-10: the V45 source tree passed Ruff, a 44-test repair scope and the
  396-passed/33-skipped integrated release scope. The immutable V45 freeze
  (`cb684e261086e343c96002ec6c69dad6927afe8c584c1b7e63339fad979584db`)
  passed 19 authority tests and the same 396-passed/33-skipped integrated scope
  without a Git object database. Pytest exited zero; frozen-tree interpreter
  teardown emitted one late Win32 `IUnknown` release diagnostic, retained for
  Windows build/install observation.
- 2026-08-10: advanced the guarded QML/current HUD authority to V11/V30 while
  restoring historical V7 bytes exactly; the focused HUD gate passed 50 tests
  with 1 expected skip.
- 2026-08-10: authenticated the 745-entry Google Workspace local closure,
  introduced build-only exclusions for the acyclic V46 release verifier, and
  passed 153 tests with 1 expected skip across activation, connector, license
  transport and Release V46.
- 2026-08-10: current-successor retirement V8 preserved nine stale historical
  test nodes byte-exact and redirected them to authenticated V30/V46 suites.
  The integrated release gate passed 270 tests; Phase 11 and cross-platform
  source gates passed 190 tests with 14 expected platform skips.
- 2026-08-10: Ruff F/E9 and security S102/S310/S314/S602 gates passed with all
  dynamic-execution and URL exceptions path-and-SHA-256 bound.
- 2026-08-10: the first V46 freeze (2,729 files; root
  `3508a125230493f547b21e0e7a52146c514fc6e148bffa68d10c60d0b49e4f95`)
  was preserved as diagnostic after frozen validation exposed one test-only
  dependency on the intentionally excluded `.venv/Scripts/pythonw.exe`.
  The V24 harness now skips that local-virtualenv integration only when the
  executable is absent; source/runtime authentication remains unchanged.
- 2026-08-11: authenticated R8 replaced the failed first V46 freeze with a
  2,729-file source root
  `092df168843ae1328fac93ff1005cfd810fb4f1b1396e045b993947df164f032`;
  its authority scope passed 310 tests with 5 expected skips.
- 2026-08-11: R8B produced exact Setup and portable artifacts, installed with
  exit code 0, matched all 7,473 bundle files with zero missing or mismatched
  hashes, and relaunched the byte-identical 1.1.9 executable.
- 2026-08-11: installed text-command identity persisted as `Sir` across
  restart; provider response, idle/speaking Orb motion, short CPU/memory and
  representative mission/recovery gates passed. Physical microphone and
  owner-heard acoustic quality remain manual gates.
- 2026-08-11: generated the exact unsigned Windows R8B technical SPDX
  (`86897c1a...e006`) covering both artifacts, the bundle inventory and 112
  shipped distributions; legal and final signed all-platform SBOM gates remain
  open.
- 2026-08-11: started the corrected 28,800-second R8B installed monitor at
  2026-08-11T04:24:48Z; its terminal result is not yet claimed.
- 2026-08-11: rebound the technical license worklist and intentionally blank
  legal-approval template to the exact R8B artifact, bundle and SBOM hashes;
  the unchanged 112-distribution/175-legal-file inventory is technical
  evidence only. Release/documentation validation passed 53 tests with 1
  expected skip, followed by 10/10 legal-document routing tests.
- 2026-08-11: current source-entrypoint Ruff gates F/E9 and security
  S102/S310/S314/S602 passed. A repository-root scan also inspected deliberate
  tamper fixtures under untracked `.test-temp/`; those fixture findings are not
  product-source findings and were not changed.
- 2026-08-11: `pip-audit` identified nine known vulnerabilities in the R8B-era
  lock across five distributions. The V47 successor upgraded `curl-cffi`,
  `h2`, `mcp`, `pypdf` and `werkzeug`, declared the clean-env PDF dependency,
  regenerated the hash-pinned lock and then reported no known vulnerabilities.
- 2026-08-11: a clean Python 3.13 environment synchronized 150 Windows
  distributions from the new lock and passed 170 focused tests with 1 expected
  platform skip. Phase 5 V47, successor-retirement V9 and Release V47 then
  passed their six-test documentation/authentication scope.
- 2026-08-11: cross-platform dry resolution found that the macOS workflow's
  all-wheel policy could not install PyAutoGUI's source-only helpers. V47 now
  limits wheel-only enforcement to `cryptography`; hash-enforced resolution
  passes for macOS arm64 (145 packages) and Ubuntu 24.04 Linux x64/arm64 (141
  packages each), without claiming native runtime qualification.
- 2026-08-11: corrected the source freezer's current-authority selector from
  V46 to exact Phase 5/Release V47. The R9 freeze can no longer silently bind
  the superseded release envelope.
- 2026-08-11: the first clean-lock full suite recorded 49,233 passed, 116
  skipped, 673 subtests, 156 failures and one error. The result is retained as
  diagnostic evidence; its Phase 11 cascade came from a harness temporary root
  outside the required LocalAppData boundary, not from a weakened sandbox.
- 2026-08-11: advanced current authority to V48, rebound Capability Nexus to
  the current permission broker, added exact additive Phase 5 retirement V2,
  authenticated 60 unique historical nodes, refreshed the 743-module Google
  Workspace closure and corrected the Orb motion driver to target the current
  cinematic QML root. Transition tests passed 4/4 and Google Workspace passed
  50/50.
- 2026-08-11: a 42,003-case regression exposed only two remaining findings
  plus a terminal-close error. Stable issuer time binding and the short,
  LocalAppData-contained Win32 harness root then passed the exact 37-test
  correction scope; a new uninterrupted full-suite receipt remains required.
- 2026-08-11: uninterrupted R4 completed 49,374 passed, 116 skipped and 700
  subtests in 4,533.52 seconds. Its seven failures were six superseded
  V2/V9/V10/V19 test nodes plus the stale SHA-256 binding for the current
  Google Workspace Ruff exception; no runtime-engine failure or pytest
  infrastructure error remained. V48 now routes those six nodes additively and
  rebinds the current exception to exact current bytes.
- 2026-08-11: uninterrupted clean-lock R5 passed 49,381 tests, 116 expected
  skips and 700 subtests in 4,492.70 seconds. Its JUnit records 50,197 cases,
  zero failures and zero errors. A 67-byte stderr cleanup diagnostic reports a
  Windows `IUnknown` release exception after pytest completion; it did not
  change the zero exit result or JUnit outcome. The mutable-source full-suite
  gate is closed and R9 freeze/build/install is now the active release step.
- 2026-08-11: froze V49 R10B (2,769 files; root `f9b169d1...a50`), built Setup
  `bd2a7c5...27d16` and portable `2dc03067...fbd2`, installed successfully and
  matched 7,451/7,451 bundle files with no missing or mismatched bytes.
- 2026-08-11: the official installed harness passed all nine governed scopes;
  direct Orb frames differed across 83.8998% of sampled central pixels and the
  visible 30-second sample used 0.39% of total machine CPU capacity.
- 2026-08-11: added the deterministic release-compliance reconciler and two
  fail-closed tests. The real R10B run passed exact Setup/portable/SBOM/bundle/
  installed/legal-evidence binding and emitted receipt SHA-256
  `7aeefaeebb22a1becb93b0a568756234918c259a408dfaae6a9a7dc33ddb6e6f`;
  legal approval and public eligibility remain false.
- 2026-08-11: consolidated current navigation into the R10B status, evidence
  index and supersession registry while retaining R8B/V48 and earlier evidence
  as immutable predecessor history.
- 2026-08-11: authenticated Release V50 over immutable V49, binding 86 current
  release/evidence paths. Its verifier confirms unchanged Phase 5 V49 runtime
  authority and keeps formal readiness and publication false.
- 2026-08-11: the expanded release selection first hit 73 Windows temp-root
  permission errors, then reached 150 passed/1 skipped with one real stale-test
  failure: the PyInstaller discovery fixture still staged HUD V30 while the
  production package gate verifies V31. The fixture now stages the exact V31
  manifest and predecessor closure.
- 2026-08-11: corrected the long-session receipt so unobserved microphone,
  playback and Gemini receive counters report `not_proven`, never a fabricated
  voice pass. Four monitor tests passed. The exact R10B 28,800-second
  performance monitor started at 2026-08-11T14:58:47Z with this honest scope.
- 2026-08-11: corrected the direct `check_release_eligibility.py` entrypoint to
  resolve the project root before importing `core`. Its 23-test unittest module
  passed with one expected skip, and the real R10B command now blocks cleanly
  on unsigned/untrusted Windows evidence plus absent legal/repository approval,
  instead of crashing with `ModuleNotFoundError`.
- 2026-08-11: extended the additive Phase 5 evidence selector to V50 over the
  immutable V49 fixture. It rebinds only current file hashes, preserves all
  historical/predecessor identities and does not add a new runtime change; the
  inherited Phase 5 policy remains byte-identical to V49.
- 2026-08-11: made the independently authenticated Release V50 record the
  global current release selector, binding 91 current evidence paths without
  changing installed runtime authority. The focused successor/compliance/
  monitor/documentation gate passed 10 tests; the expanded release gate passed
  152 tests with 1 expected skip; targeted Ruff F/E9 and security checks passed.
- 2026-08-11: corrected seven stale documentation headers that still routed
  readers through V31/V41. Their historical evidence bodies remain unchanged,
  while each header now points directly to the R10B current-status and
  supersession authorities; the focused documentation gate passed 3 tests.
- 2026-08-11: audited the first R10B long-session attempt and rejected its
  stale `in_progress` receipt after both the Onyx process and monitor ended at
  2,103.814 seconds. Relaunched the exact installed executable
  `2e22c12f...d6b` and started isolated attempt 3 at
  2026-08-11T15:42:53Z against PID 32064; terminal acceptance remains open.
- 2026-08-11: an intentionally broad 24-file diagnostic glob executed retired
  V42-V49 authority tests directly and produced 15 predecessor-current
  failures (24 passed). Those historical nodes are not a current gate and were
  not rewritten. The authoritative V50 documentation/Phase 5/monitor/
  compliance/eligibility selection passed 33 tests with 1 expected skip.
- 2026-08-11: bound all eight R10B runtime `NOASSERTION` rows into a strict
  engineering decision packet. Seven version-tag license candidates match the
  shipped legal bytes (`pycaw` after newline normalization only); `odfpy`
  remains substantively unresolved, legally approved remains 0 and public
  eligibility remains false. Release V50 now authenticates 101 current paths;
  the authoritative gate passed 36 tests with 1 expected skip, followed by
  targeted Ruff F/E9/security checks.
- 2026-08-11: replaced the non-identical rebuild/publish route with an exact
  multi-run qualification chain. Release artifacts are retained from one
  successful build run, native lifecycle and eight-hour evidence bind those
  same bytes, protected independent review emits canonical provenance, and an
  explicit publish dispatch re-downloads and verifies the same build and
  qualification runs before GitHub release publication.
- 2026-08-11: added fail-closed artifact resolution, final provenance and
  qualification verification, architecture-specific technical SPDX names and
  ephemeral Windows/macOS/Linux runner jobs. The 18-test qualification scope
  passed both isolated and repository-global collection; targeted Ruff F/E9/S
  gates passed. No remote native runner, signing credential, notarization or
  protected-environment approval was claimed from this local source result.
- 2026-08-11: advanced the additive evidence selectors to Phase 5/Release V51
  without changing runtime authority. Retirement V11 preserves three V49/V50
  historical nodes and redirects them to SHA-256-bound V51 successors; the
  six-test global retirement selection passed.
- 2026-08-11: removed the publish-time SBOM regeneration gap. The formal build
  now emits one aggregate SBOM only after all four target artifacts and native
  Windows trust receipt exist; qualification provenance binds the SBOM and its
  digest, and publication reuses those exact reviewed bytes. Two new tamper
  regressions bring the focused qualification scope to 18 passed tests.
- 2026-08-11: constrained build and native-qualification artifacts to exact
  name allowlists before merge/download. Qualification and publication now
  reject missing, duplicated, expired or unexpected artifact containers rather
  than merely checking that the required names are present.
- 2026-08-11: corrected the source freezer from stale Phase 5/Release V48 to
  exact V51 authorities. Retirement V12 preserves the V48 selector tests and
  routes them to the SHA-256-bound V51 freezer test; the correction changes
  release traceability only and does not alter runtime authority.
- 2026-08-11: added an independent fail-closed source-freeze verifier covering
  canonical manifest structure, exact tree membership, every size/hash, the
  aggregate root, Git-state shape and both V51 authorities. Its two tamper
  tests passed, and it independently verified the first R11 freeze of 2,803
  files/root `54670ba2...052e`; that freeze remains pre-verifier source evidence.
- 2026-08-11: hardened long-session JSON/CSV publication against transient
  Windows reader locks. Attempt 3 remains rejected after its unhandled lock
  and three absent-window samples; clean attempt 4 started against the same
  installed executable/PID without rewriting the diagnostic receipt.
- 2026-08-11: the R15B build failed closed before copy/build when the frozen
  SQLite seed had drifted. The exact manifest bytes were restored from the
  matching authenticated source seed, 64 generated bytecode files were moved
  to an external quarantine, the 2,821-file tree reverified to root
  `346dcba1...f45`, and the incident was retained as explicit evidence.
- 2026-08-11: replaced the impossible path-bound verification of a relocated
  build workspace with an exact membership/size/hash/root relocation gate.
  Its two fail-closed tests passed and the real R15B isolated copy passed before
  the Windows build began.
- 2026-08-11: validated the Win32 `PrintWindow` capture/delta/resource
  primitives against a real animated Qt window and added a fail-closed final
  evidence index generator whose four index/consolidation tests passed.
- 2026-08-11: added a post-build source-input preservation gate. It permits
  generated build/release outputs but rehashes every frozen manifest input and
  blocks installation on any missing or changed source byte; three focused
  relocation tests passed.
- 2026-08-11: the first parallel R15B artifact build reached the isolated Setup
  install smoke, then timed out after 300 seconds because the production R10B
  process was intentionally still resident for its protected soak. No R15B
  install occurred. The leaked temporary Inno child was terminated by exact
  path/name and both temporary trees were moved into the failed-workspace
  archive; the build log and failed watcher states remain retained.
- 2026-08-11: armed a fail-closed post-soak recovery watcher. It accepts only a
  terminal full-duration/responsive/error-free R10B receipt, requests the
  authenticated installer-maintenance shutdown, archives the rejected R15B
  workspace/evidence, rebuilds the same frozen source, waits for a fresh build
  state and then rearms post-build hashing, install, Linux-container,
  live-window and consolidation watchers. PowerShell parsing passed.
- 2026-08-11: reverified both trees after the rejected artifact attempt. The
  immutable source still matches 2,821 files/root `346dcba1...f45`; the failed
  build workspace preserves every manifest input byte with generated outputs
  allowed. Receipt SHA-256: `44ab4a71...74d0`; it is diagnostic and explicitly
  not public-release evidence.
- 2026-08-11: the isolated no-network Linux build exposed two distinct
  release-evidence dependencies rather than weakening the container boundary.
  The first archived run reached the frozen missing-distribution license
  generator and failed when it attempted network retrieval. A hash-bound cache
  then supplied all 11 exact URLs, after which a second archived run exposed
  the separate `primp` PyPI/license-tree dependency. Both workspaces and logs
  remain preserved as rejected diagnostic evidence.
- 2026-08-11: added an external, fail-closed offline license-evidence runner
  without modifying the 2,821 frozen source bytes. Cache v2 binds the source
  manifest (`416ec711...3a5`), both frozen license modules, all 11 URL objects,
  the missing-distribution spec fingerprint and the exact Linux x86_64
  `primp` evidence tree (`3ca635dc...7f93`). Its manifest SHA-256 is
  `a6915d80...1bfe`; two focused tests, Ruff and both PowerShell parsers passed.
  The third isolated build then failed closed because its V3 validation image
  contained five runtime versions that drifted from the frozen lock
  (`curl-cffi`, `h2`, `mcp`, `pypdf` and `werkzeug`); that complete workspace is
  retained under `linux-preflight-sbom-lock-gap-20260811T194549`.
- 2026-08-11: built validation image V4 from the exact frozen Linux lock and
  verified all 141 active requirements with zero mismatches and no network.
  The resumed build produced DEB SHA-256 `4d8f4477...90c8`, TAR SHA-256
  `e3ff2840...6b3` and SPDX SHA-256 `c3b67c55...422e`; all 109 bundled runtime
  distributions match the frozen lock exactly.
- 2026-08-11: preserved the clean-smoke failure caused by an insecure inherited
  HOME mode plus a stale verifier expectation, then reran the exact DEB in a
  no-network disposable Debian image with a 0700 UID/GID-bound tmpfs HOME. The
  installed executable returned the expected `passed_limited` safe-unavailability
  contract with zero network, process or provider calls. Container-gate receipt
  SHA-256: `57557e9ae420b1050036cec1259f70c1ce930fa50ad2374332ee4db59a9ad58f`.
  Native Linux desktop, audio, signal, session and lifecycle evidence remains
  open and public eligibility remains false.
- 2026-08-11: independently reopened the Linux gate and recalculated every
  source-manifest, validation-image, DEB, TAR, release-manifest, inventory,
  frozen-lock, SPDX, offline-license and clean-smoke binding. Three adversarial
  verifier tests and Ruff passed; independent receipt SHA-256
  `e6a43cbe638a05c33a7b4925c828f863f530a99052645a2489108953fc641c6c`.
- 2026-08-11: independently preflighted the live post-soak recovery chain
  without starting, stopping, building or installing anything. The verifier
  rehashed the exact 2,821-file frozen source, bound the V4 validation image
  and offline-license cache, confirmed one live recovery watcher (PID 48800),
  parsed all seven PowerShell orchestration scripts and required the
  authenticated shutdown, fresh-build-state, owner, Orb and downstream gate
  contracts. Three adversarial tests and Ruff passed; receipt SHA-256
  `0656e7917bd3ae1a837413f03a74bea981fd3b095b5ec11ed7dd3aa189e71690`.
  The seven-document current-authority verifier then passed against the updated
  status/index/registry set; documentation receipt SHA-256
  `54befe7917c13fc531c503e673ffc9796622c3638e6b2329aa901ec68d5a7b49`.

## R15B post-freeze execution record

- [x] Exact V53 source frozen: 2,821 files, 141,905,982 bytes, root SHA-256
  `346dcba124fceb30de34c2502164c9ef01e1b8a7350b35d362fd3aee2f3e0f45`.
- [x] Expanded frozen Windows suite, portable security gate, release gate and
  Linux-container source suite passed without modifying the frozen tree.
- [x] Live Microsoft Graph DayOps read/refresh/rotation gate passed with
  `Calendars.Read`, `Mail.Read`, `offline_access` and `User.Read`.
- [x] Live Gemini native-audio provider returned a 2.44-second, 24 kHz mono WAV;
  physical microphone and owner-heard quality remain explicitly unproven.
- [x] Installed Orb verifier passed its R10B compatibility dry-run: 22 exact
  source/install bindings, 100-file packaged HUD contract, distinct listening
  and speaking frames, reduced-motion/hidden quiescence and bounded off-screen
  software-renderer resources.
- [x] R15B install watcher is wired to run technical, owner-name and Orb gates
  before launching the exact installed executable and starting its eight-hour
  soak; the recovery watcher will rearm it after the protected R10B shutdown.
- [x] Fail-closed R15B consolidation watcher is wired to bind Windows, DayOps,
  voice, Orb, soak and Linux-container evidence without claiming public
  eligibility or any external gate; it will be rearmed by recovery.
- [x] Read-only live-window watcher is wired to capture two direct frames,
  detect central Orb motion and sample 30 seconds of the exact executable's
  CPU/memory/responsiveness without clicking or issuing commands; it will be
  rearmed by recovery.
- [x] R15B relocated build workspace passed exact membership, byte, aggregate
  root and manifest binding; the first artifact attempt failed only at the
  isolated Setup install smoke while R10B remained resident and is retained as
  rejected evidence.
- [x] Final local evidence-index generation is wired after consolidation and
  remains explicitly `not_performed` for independent review and public NO-GO.
- [x] Post-build input preservation is wired as a mandatory pre-install gate;
  it will reverify all 2,821 frozen inputs after artifact generation.
- [x] The armed recovery chain passed an independent, fail-closed preflight of
  its exact source, hashes, validation image, live watcher identity and all
  downstream PowerShell contracts; execution remains soak-gated.
- [ ] R10B terminal soak releases the protected R15B recovery/rebuild/install
  sequence.
- [ ] Exact R15B Windows build, install, startup and eight-hour soak pass.
- [x] R15B Linux-container build/package/disposable-DEB gate passes within its
  recorded no-network, safe-limited preflight scope.
- [ ] Native Linux and macOS GUI/audio/lifecycle gates pass on real hosts.
- [ ] Windows signing, macOS signing/notarization, legal approval, final SBOM,
  all-platform clean-host lifecycle and independent evidence review pass.

## Change Log

- 2026-08-10: advanced the source successor through V44, recorded the failed
  V41 Linux package preflight and non-hermetic V42/V43 freezes, and refreshed
  the current release evidence boundary.
- 2026-08-10: advanced the hermetic source successor to V45, authenticated HUD
  V29, and froze and revalidated the exact 2,710-file source candidate while the
  independent V41 installed soak continued.
- 2026-08-10: advanced the mutable successor to HUD V30, Phase 5 V46, Release
  V46 and retirement V8; preserved V45 and all earlier authorities as immutable
  predecessors and prepared the V46-aware source freezer.
- 2026-08-11: froze authenticated source R8, built and installed Windows R8B,
  consolidated installed evidence, generated its technical SPDX, updated
  documentation precedence and began the corrected eight-hour qualification.
- 2026-08-11: rebound technical license/legal-review materials to R8B without
  fabricating the still-required human approval.
- 2026-08-11: superseded R8B for final-release use, advanced the mutable
  security successor to Phase 5/Release V47 and preserved V46/R8B as exact
  historical evidence while the installed stability monitor continues.
- 2026-08-11: corrected the macOS dependency installation policy so the
  cross-platform workflow is resolvable while retaining a wheel-only boundary
  for the security-sensitive `cryptography` distribution.
- 2026-08-11: made V47 the explicit source-freeze authority and added a focused
  regression test rejecting the superseded V46 selector.
- 2026-08-11: superseded mutable V47 with evidence-corrected V48 without
  rebinding any predecessor; prepared the clean uninterrupted R4 full-suite
  gate before any R9 freeze or artifact rebuild.
- 2026-08-11: retained R4 as diagnostic evidence and prepared R5 after closing
  its seven evidence-only failures without rewriting predecessor artifacts.
- 2026-08-11: completed clean R5 with 49,381 passed, 116 skipped and 700
  subtests; promoted V48 from focused-only evidence to a passed full-suite
  source successor, without claiming artifact or public-release readiness.
- 2026-08-11: froze, built and installed R10B; added exact Windows compliance
  reconciliation and updated current documentation authority without claiming
  signing, legal, native cross-platform or independent-review completion.
- 2026-08-11: authenticated the post-R10B evidence changes as acyclic Release
  V50 without changing the runtime selector or rebinding V49 history.
- 2026-08-11: corrected the current native-release discovery test from the
  superseded HUD V30 fixture closure to current HUD V31.
- 2026-08-11: started the exact R10B eight-hour performance soak after making
  the voice-rotation sub-gate fail honest when it was not observed.
- 2026-08-11: repaired the public-eligibility direct CLI path and added a
  regression proving it resolves `core` from an arbitrary working directory.
- 2026-08-11: advanced the additive evidence selector to Phase 5 V50 so current
  release-tool hashes are authenticated without widening runtime authority.
- 2026-08-11: promoted authenticated Release V50 to the global current release
  selector and revalidated focused plus expanded release gates without
  rewriting immutable V49 or earlier evidence.
- 2026-08-11: consolidated stale roadmap/V31/V41 document precedence directly
  under the R10B registry and added a regression requiring those in-file
  supersession markers.
- 2026-08-11: invalidated the non-terminal first R10B soak for release use and
  restarted the exact installed candidate under a separately retained
  attempt-3 receipt without widening the performance-only evidence scope.
- 2026-08-11: added the exact R10B tag-bound legal decision packet and its
  fail-closed verifier without changing SBOM declarations or fabricating legal
  approval; seven candidates are technically reconciled and `odfpy` remains
  open for an authorized human decision.
- 2026-08-11: implemented the exact-byte native qualification and explicit
  publish pipeline, authenticated it as Phase 5/Release V51, and registered
  superseded V49/V50 current-selector tests under retirement V11 without
  rewriting historical fixtures or widening the installed runtime.
- 2026-08-11: made the aggregate formal SBOM a retained build artifact bound
  by final qualification, eliminating post-qualification SBOM regeneration.
- 2026-08-11: added exact build-run and qualification-run artifact allowlists
  before evidence assembly and public-release download.
- 2026-08-11: advanced the deterministic source-freeze selector to exact
  Phase 5/Release V51 and authenticated the superseded V48 selector through
  retirement V12.
- 2026-08-11: added durable independent verification for source-freeze
  membership, bytes, aggregate root and V51 authorities before final rebuild.
- 2026-08-11: retained the R15B freeze-drift/build-gate failures, hardened
  evidence publication and relocation verification, started clean R10B attempt
  4, and resumed a verified parallel R15B Windows build without touching the
  installed Onyx.
- 2026-08-11: retained the parallel-build Setup-smoke timeout, archived its
  leaked temporary installer trees, and rearmed a full post-soak rebuild plus
  downstream acceptance chain without changing the frozen R15B bytes.
- 2026-08-11: established the R15B supersession registry as the current
  navigation authority, corrected the current status/evidence index for V53,
  attempt 4, live DayOps and live native audio, and added a fail-closed
  documentation verifier. The verifier passed seven authorities and its three
  focused tests passed; durable receipt SHA-256
  `16516908806f9cb7e18917f91676ab8ff6a1337ceedaca5d00ee7c5b62b08cfb`;
  public eligibility remains false.
- 2026-08-11: added an explicit independent-source mode to the reusable Linux
  container/package gate and started an isolated R15B DEB/TAR/SBOM/clean-install
  preflight while the Windows predecessor soak continues. This mode does not
  claim Windows installed acceptance or native Linux desktop/audio evidence.
- 2026-08-11: corrected the Linux gate to suppress bytecode in the immutable
  source and use the exact relocated-workspace verifier for isolated copies.
  Two pre-build failures were archived without deleting evidence; the source
  freeze was restored to exact membership and reverified, the relocated copy
  passed, and the recovery watcher was safely restarted as PID 37260 with the
  corrected arguments while Onyx and its soak monitor remained untouched.
- 2026-08-11: preserved two further Linux failures that proved independent
  online legal-evidence dependencies, then introduced an external hash-bound
  offline cache/runner around the frozen builder. Cache v2 includes all 11
  primary-source objects plus exact Linux `primp` evidence and is being
  exercised under Docker `--network none`; no Linux pass is claimed before the
  terminal build and clean-install receipts exist.
- 2026-08-11: replaced the drifted V3 Linux validation environment with an
  exact-lock V4 image, reconciled all 109 bundled distributions and the SPDX,
  and passed the disposable DEB install plus portable safe-unavailability smoke
  under a secure ephemeral HOME. The bounded container preflight is closed;
  native Linux GUI/audio and full lifecycle qualification remain open.
- 2026-08-11: added and executed a separate fail-closed verifier for the Linux
  container receipt. It passed the actual artifacts and rejects artifact tamper
  or any false widening of native/public status.
- 2026-08-17/19: executed the full R15B chain to a consolidated local
  acceptance. The exact frozen candidate was rebuilt after an authenticated
  cooperative shutdown of the predecessor, installed under custody, and passed
  the installed technical, owner-name (transcript authority with fresh
  activation restart persistence) and installed-orb acceptances, plus a
  visible packaged-window ambient-orb capture. Installed executable SHA-256
  `ff289de8b8c607586ae580949359568805a54f928edda92b44efe9d39cb8cda7`.
- 2026-08-18/19: the terminal eight-hour Windows soak **passed** —
  28,800.04 observed seconds, 480 samples, `all_responsive=true`,
  `full_duration=true`, zero application errors; receipt SHA-256
  `127c6b18f98375da8f488c623900d2a558f0a7b5f7ff0da7fa757e71cc68b634`.
  Four earlier monitor generations were retired honestly rather than promoted:
  three latched non-responsive on transient five-second polls during owner
  desktop activity, and one monitor process died at sample 469/480 when an
  external receipt read raced its atomic write. The finalizer now auto-retries
  exactly those two classes, and reading the live receipt during a soak is
  prohibited (status is read from the append-only samples CSV).
- 2026-08-19: **finding — the Linux artifact set is not byte-reproducible.**
  Rebuilding from the identical frozen source, same pinned validation image and
  same `SOURCE_DATE_EPOCH`, reproduced 6,933 of 6,937 packaged files exactly
  but diverged in `Onyx/Onyx-DayOps` and `Onyx/_internal/base_library.zip`
  (PyInstaller archive non-determinism), changing the DEB/TAR/SPDX hashes.
  Recorded at
  `r15b-linux-container/ONYX_1_1_9_R15B_LINUX_REPRODUCIBILITY_FINDING.md`,
  SHA-256 `9f2dbffb40d4dd566644726e51438af3c7b8d16785b2f55c09488d262c92735f`.
  No hash was re-pinned to hide it; the consolidated receipt lists
  `linux_artifact_cross_build_byte_reproducibility` as **not proven**.
- 2026-08-19: **second finding — the candidate's own clean-install script is
  stale.** `packaging/linux/verify_deb_clean_install.sh` (2026-08-03) asserts
  `"status": "passed"` while the frozen product correctly reports
  `"status": "passed_limited"` with `safe_unavailability` on Linux, so it
  rejects its own valid receipt. Orchestration now carries an explicit
  verifier that runs every frozen check unchanged and corrects only that
  terminal predicate to `passed | (passed_limited AND safe_unavailability)`.
  The frozen candidate was not modified; the repair belongs to the next
  candidate.
- 2026-08-19: **consolidated local acceptance written** —
  `ONYX_1_1_9_V53_R15B_CONSOLIDATED_ACCEPTANCE.json`, SHA-256
  `b6266dfcdc9441901cfe57d2a502d3a74a6f9c9baf11d8b7533cba2437411cd6`,
  status `passed_local_windows_and_container_acceptance`, 14 bound inputs,
  10 proven items and 12 explicitly not-proven items. The consolidator was
  hardened to require an explicit `cross_build_reproducibility` declaration
  and to reject a false claim in either direction, with a hash-bound finding
  mandatory when reproducibility is not proven; its suite grew from 3 to 9
  tests. `formal_public_release_eligible` remains **false** and the release
  stays `BLOCKED_BY_LICENSE`.

## Superseded pre-fix source-gate result

The result below belongs to V9-era source succession and is retained as
historical evidence. It is not build authorization for the current tree.

- Focused release/version/preparation/eligibility/documentation/hygiene/hash
  suite: **64 passed**.
- Ruff on the changed Python surfaces: **passed**.
- V9 record SHA-256:
  `27991fabab95e3220ab34d86aec00a29d84ba49a82dc6e1ea075dc8662ca2200`.
- V9 current root SHA-256:
  `bb16f4cf23ae75919e5d6fb05ddb30adcb814e537b73778c8744d80e6e1e9671`.
