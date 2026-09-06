# ONYX-REL-1.1.9-P0-BUILD-GATE - Portable Security and Build-Gate Repair

## Status

**Done**

## Standalone corrective scope

This is the immediate P0 correction block from the owner-approved final release
roadmap. It does not replace `ONYX-REL-1.1.9.md`, alter the established Windows
engine, or claim that a distributable exists. The current installed product
remains Onyx 1.1.9 Windows x64 V31; the current worktree remains source-only and
formally not release-eligible.

The current checkout is heavily mixed and contains unrelated modified,
deleted, staged and untracked work. Implementation is limited to the exact file
surfaces listed in this story. No Git staging, reset, restore, clean, branch
switch, commit, push, installation or release is authorized by this story.

## Executor Assignment

```yaml
executor: "@dev"
quality_gate: "@architect"
quality_gate_tools:
  - focused pytest build and package suites
  - manifest and staged-tree adversarial review
  - locked-environment dependency inventory
  - independent QA regression review
```

## Story

**As the** Onyx release owner,  
**I want** the curated runtime staging boundary and local build environment to
fail closed while accepting only the already approved QML runtime closure,  
**so that** the next Windows candidate can be built from traceable inputs
without absorbing unrelated source-only HUD files or weakening portable
security.

## Observed baseline

- Portable/POSIX focused host-compatible selection: **84 passed, 30 skipped**;
  the skips require a native POSIX host.
- Broader build/package selection: **108 passed, 11 skipped, 6 failed**.
- Three failures are the same product defect: `stage_runtime_sources()` copies
  the entire source `qml/` tree, while the authenticated packaged-runtime
  manifest allows a smaller runtime QML set. Newly added, currently unwired
  cinematic-operations QML therefore crosses the staging boundary and the
  package contract rejects it.
- Three failures are an environment prerequisite: both local virtual
  environments lack the locked `werkzeug==3.1.4` distribution required by
  `requirements.txt`, so runtime-distribution inventory cannot execute.
- No artifact was built and no installed runtime was changed while collecting
  this evidence.

## Acceptance Criteria

1. Runtime staging copies QML by an explicit authenticated allowlist, not by
   recursively copying every source-side QML file.
2. Every staged QML file is individually hash-bound by the packaged-runtime
   manifest; exact-set membership alone is not accepted as byte provenance.
3. Source-only or not-yet-wired cinematic operations QML remains in the
   checkout and is excluded from the current package without deletion or
   modification.
4. Coordinated manifest tamper, unlisted QML addition, omission, symlink and
   byte tamper all fail closed.
5. The V24 stable Windows activation, voice, owner identity, permissions and
   HUD semantics are unchanged.
6. The locked build environment resolves every active runtime distribution,
   including `werkzeug==3.1.4`, without editing dependency pins.
7. The focused portable/POSIX suite and the build/package suite pass on the
   Windows source host; native POSIX skips remain reported as unclosed native
   evidence.
8. Ruff and Python compilation pass for every changed Python surface.
9. An independent Architecture/QA review confirms that the change narrows
   packaging authority and does not promote source tests into artifact,
   installed-host or release evidence.

## Tasks / Subtasks

- [x] Task 1 - Harden the packaged QML boundary (AC: 1-5)
  - [x] Define the approved packaged QML file set in the existing frozen HUD
    contract.
  - [x] Stage only those files with canonical-path, regular-file and no-link
    checks already provided by `_copy_relative()`.
  - [x] Require every approved QML path to be present in `required_files` with
    its SHA-256, and reject any set/hash divergence.
  - [x] Preserve every current source-only QML file unchanged.
- [x] Task 2 - Add adversarial regression coverage (AC: 1-5)
  - [x] Prove an unrelated QML source file is not staged.
  - [x] Prove all staged QML paths are individually bound by the manifest.
  - [x] Prove source manifest drift and staged QML tamper fail closed.
- [x] Task 3 - Restore the locked build-test environment (AC: 6)
  - [x] Install the existing hash-locked requirements into the isolated release
    virtual environment; do not change pins to fit the host.
  - [x] Re-run runtime-distribution inventory from that environment.
- [x] Task 4 - Execute bounded gates (AC: 7-9)
  - [x] Run focused portable/POSIX tests.
  - [x] Run build, hygiene, bootstrap, inventory, formal-contract and release
    eligibility tests.
  - [x] Run Ruff and `py_compile` on changed Python files.
  - [x] Record exact pass/skip/fail counts; independent verdicts remain owned
    by Architecture/QA review.

## Dev Notes

### Relevant implementation surfaces

- `scripts/package_hygiene.py::stage_runtime_sources` currently authenticates
  V26 source state, copies curated Python/scripts, then recursively copies the
  whole `qml/` directory before verifying the packaged subset.
- `core/onyx_packaged_runtime_hud_contract_v1.py` owns the compiled manifest
  digest, exact sets, required-file hashes, forbidden paths and artifact root.
- `core/onyx_packaged_runtime_hud_contract_v1.manifest.json` names the currently
  approved packaged QML paths and their hashes.
- `scripts/generate_hud_v26_manifests.py` must not turn arbitrary source-tree
  membership into package authority.
- `tests/test_package_hygiene_v1.py` and
  `tests/test_packaged_runtime_hud_contract_v1.py` are the primary regression
  surfaces; `tests/test_native_release_gate_v1.py` proves PyInstaller input
  discovery.

### Security boundary

The package manifest is an allowlist and byte-provenance record. Broad source
globs may detect unexpected files but must never automatically authorize them
for shipment. Source-only cinematic operations QML is preserved for its own
future wiring/acceptance story.

### Project architecture guidance

No release-specific architecture shard is available in the AEXOS framework
documents. The authoritative constraints for this story are the current release
status, the frozen HUD contract and its tests:

- `docs/onyx/CURRENT_RELEASE_STATUS.md#exact-current-boundary`
- `docs/onyx/CURRENT_RELEASE_STATUS.md#gate-matrix`
- `core/onyx_packaged_runtime_hud_contract_v1.py`
- `scripts/package_hygiene.py`

### Testing

- Use repository-local test modules with a unique existing-parent Windows temp
  directory for `--basetemp`; the nested repository path may fail before tests
  when its parent is absent.
- Preserve native Linux/macOS skips as skips; do not mock them into passes.
- A green source suite is not an artifact or installed-host acceptance result.

## CodeRabbit Integration

### Story Type Analysis

**Primary Type:** Security  
**Secondary Types:** Deployment, Architecture  
**Complexity:** High - the change affects authenticated package membership and
the release input boundary.

### Specialized Agent Assignment

**Primary Agents:**

- `@dev` - implementation and pre-commit review
- `@architect` - trust-boundary quality gate

**Supporting Agents:**

- `@qa` - adversarial manifest/staging verification
- `@devops` - later build/PR work only under separate authorization

### Quality Gate Tasks

- [x] Pre-Commit (`@dev`): manual exact-surface review completed; CodeRabbit
  unavailable because the configured WSL environment has no `bash`.
- [ ] Pre-PR (`@devops`): deferred; this story authorizes no Git publication.
- [ ] Pre-Deployment (`@devops`): deferred to artifact and installed-host gates.

### Self-Healing Configuration

- Primary Agent: `@dev` (light mode)
- Max Iterations: 2
- Timeout: 15 minutes
- Severity Filter: CRITICAL only
- CRITICAL issues: repair and rerun affected source gates.
- HIGH issues: document and return to Architecture/QA.

### CodeRabbit Focus Areas

**Primary Focus:**

- Manifest self-authorization and broad-glob package-authority escalation.
- QML omission/addition/symlink/tamper handling.

**Secondary Focus:**

- Dependency-pin integrity and reproducible build environment.
- No regression or false promotion of Windows/POSIX evidence.

## Story Draft Checklist

- [x] Goal, value and P0 roadmap relationship are explicit.
- [x] Exact affected files and trust boundaries are identified.
- [x] Product failures are separated from environment prerequisites.
- [x] Acceptance criteria are measurable and adversarial cases are included.
- [x] Native-host, artifact, installed and release evidence boundaries remain
  explicit.

**Draft validation:** READY FOR PO REVIEW.

## Change Log

| Date | Version | Description | Author |
|---|---:|---|---|
| 2026-08-10 | 0.1.0 | Initial P0 build-gate repair story from live gate evidence | Chronos (`@sm`) |
| 2026-08-10 | 0.1.1 | Validated GO (9.7/10) - Status: Draft to Ready | Themis (`@po`) |
| 2026-08-10 | 0.2.0 | P0 implementation and authenticated V41/V34 source freeze completed; Status: Ready to Ready for Review | Vulcan (`@dev`) |
| 2026-08-10 | 0.2.1 | QA review started - Status: Ready for Review to InReview | Argus (`@qa`) |
| 2026-08-10 | 0.2.2 | QA PASS - Status: InReview to Done | Argus (`@qa`) |

## Dev Agent Record

### Agent Model Used

Codex (GPT-5)

### Debug Log References

- Portable/POSIX focused selection: 84 passed, 30 skipped.
- Build/package selection: 108 passed, 11 skipped, 6 failed.
- Red test: explicit QML allowlist test failed against broad source-tree glob.
- Curated staging smoke: 24 approved QML files staged; operations HUD excluded.
- Final build/release selection: 144 passed, 11 native-host skips.
- Final portable/POSIX selection: 84 passed, 30 native-host skips.
- Phase 5 V40/V41 and Release V33/V34 transition selection: 21 passed.
- Ruff and `py_compile`: passed on all changed Python surfaces.
- CodeRabbit: unavailable; `wsl` reported `/bin/sh: bash: not found`.

### Completion Notes List

- Replaced broad QML tree packaging with an explicit compiled 24-file
  allowlist; every member must also have an individual manifest hash.
- Preserved 11 source-only cinematic operations QML files without shipping
  them through the current V24 package path.
- Installed the unchanged hash-locked requirements into `.venv-release-v16`;
  runtime inventory now resolves `werkzeug==3.1.4` and the active closure.
- Added immutable Phase 5 V41 and Release Workflow V34 successors without
  rewriting V40/V33 or earlier records.
- No artifact, installation, Git publication, provider call or native-host
  release claim was made.

### File List

- `docs/stories/ONYX-REL-1.1.9-P0-BUILD-GATE.md`
- `core/onyx_packaged_runtime_hud_contract_v1.py`
- `docs/onyx/acceptance/VE-HUD-CURRENT-V26-E6-001.manifest.json`
- `scripts/package_hygiene.py`
- `tests/test_packaged_runtime_hud_contract_v1.py`
- `scripts/generate_phase5_current_successor_v41.py`
- `tests/fixtures/phase5_current_successor_transition_v41.json`
- `scripts/verify_phase5_exit_retirement_v1.py`
- `tests/test_phase5_current_successor_transition_v40.py`
- `tests/test_phase5_current_successor_transition_v41.py`
- `scripts/generate_release_workflow_v34.py`
- `tests/fixtures/release_workflow_transition_v34.json`
- `scripts/verify_release_workflow_v34.py`
- `docs/onyx/checkpoints/RELEASE_WORKFLOW_V34_VERIFIER_RECEIPT.json`
- `tests/test_release_workflow_transition_v33.py`
- `tests/test_release_workflow_transition_v34.py`

## QA Results

**PASS for the P0 source/build-gate layer.** Independent QA reran the manifest,
package-hygiene, portable-security, descriptor-activation, Phase 5 V41 and
Release V34 selections: **36 passed, 8 native-host skips**. Ruff passed on all
changed Python surfaces. Together with the developer evidence, the accepted
bounded totals are **144 passed / 11 native skips** for build/release and
**84 passed / 30 native skips** for portable/POSIX.

Requirements traceability:

- AC1-3: explicit 24-member packaged QML allowlist equals manifest membership;
  all 24 entries are individually hash-bound; source-only operations QML is not
  staged.
- AC4: existing adversarial tests reject staged addition, omission, byte tamper,
  coordinated manifest tamper and linked/unsafe inputs.
- AC5: no stable V24 bootstrap, voice, identity, permission or HUD execution
  file changed in this story.
- AC6: hash-locked release environment resolves `werkzeug==3.1.4` and runtime
  inventory tests pass.
- AC7-8: focused suites, Ruff and compilation pass with native-host skips kept
  explicit.
- AC9: Architecture and QA both return GO/PASS for source/build-gate scope.

Residual release risks are intentionally outside this story: no Windows
artifact/install proof, no native Linux/macOS execution, no external
zero-divergence seal, no signing/notarization and no public-release authority.

## Architecture Review Results

**GO for the P0 source/build-gate layer.** The compiled allowlist, packaged
manifest and staged tree agree on exactly 24 QML members, and all 24 have
individual SHA-256 bindings. Broad source membership no longer grants package
authority; the unwired cinematic-operations QML remains outside the staged
runtime. Phase 5 V41 authenticates V40 as predecessor, and Release Workflow V34
authenticates V33 as predecessor without modifying either historical record.

The change narrows packaging authority and does not modify the stable V24
bootstrap, voice, identity, permission or HUD execution paths. This verdict is
source/build-gate only: it does not authorize or prove an artifact, installation,
native POSIX runtime, signing, provider access or public release.
