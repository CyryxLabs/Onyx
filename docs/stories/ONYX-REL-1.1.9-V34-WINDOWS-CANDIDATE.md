# ONYX-REL-1.1.9-V34-WINDOWS-CANDIDATE - Isolated Windows Build

## Status

**Failed - Preserved Evidence**

## Executor Assignment

```yaml
executor: "@devops"
quality_gate: "@architect"
quality_gate_tools:
  - content-addressed candidate inventory
  - authenticated V41 and V34 verification
  - native build and package smoke gates
  - artifact hash and inventory review
```

## Story

**As the** Onyx release owner,  
**I want** an isolated Windows V34 candidate built from the authenticated source
closure,  
**so that** the mixed development checkout cannot contaminate or be damaged by
release cleanup and the resulting Setup/portable artifacts are traceable.

## Acceptance Criteria

1. A new candidate root is created at
   `C:/MAAX_Assistant/Onyx-V34-Windows-Candidate-20260810`; the existing Onyx
   checkout and V31 candidate are not modified by copy/build cleanup.
2. The candidate uses an explicit source allowlist, excludes virtualenvs,
   caches, runtime/rollback state, prior build/release outputs, secrets and Git
   metadata, and records canonical per-file SHA-256 plus one aggregate root.
3. Phase 5 V41, Release Workflow V34, HUD V26 and package-hygiene verification
   pass inside the isolated candidate before build.
4. The build uses the existing hash-locked `.venv-release-v16` interpreter and
   unchanged dependency pins.
5. Windows Setup and portable artifacts are produced with provider-free native
   smoke, package structure and entrypoint gates passing.
6. Artifact inventory, SHA-256, size, build-input seal and diagnostic exception
   (`windows_authenticode_untrusted` until signing) are recorded.
7. No installation, upgrade, uninstall, signing, provider call, Git mutation or
   public release is performed by this story.
8. Architecture and QA independently review the candidate-bound evidence.

## Tasks / Subtasks

- [ ] Freeze isolated source candidate and inventory it (AC: 1-4).
- [ ] Run authenticated source/preflight gates inside the candidate (AC: 3).
- [ ] Build Windows Setup and portable artifacts (AC: 4-6).
- [ ] Verify artifacts and record exact evidence (AC: 5-8).

## Build Result

- Source freeze completed: 2,611 files, 139,609,401 bytes, aggregate root
  `ce9e0883ab082afcdde286b778f1286aee045372db12e235a2f3ee8f54dd20a4`.
- Authenticated V41/V34, HUD V26, package hygiene and 43 focused tests passed
  inside the isolated candidate.
- PyInstaller produced the bundle, but the first executable package smoke
  failed closed with exit code `70`; Setup and portable artifacts were not
  produced.
- `build/smoke-data/runtime/logs/onyx-bootstrap-diagnostic.log` proves an exact
  membership conflict: runtime docs shipped the required V19 HUD manifest while
  the frozen package contract admitted only V20-V25.
- The V34 candidate is preserved unchanged. Remediation continues under
  `ONYX-REL-1.1.9-P0-COMPOSED-PACKAGE-GATE` and requires a new source freeze.

## Dev Notes

- `scripts/build_release.py` archives/cleans `release/` and cleans generated
  build paths; it must run only in the isolated candidate.
- The build input discovery includes fresh generated staging directories, so
  the isolated root must not carry old `build/` or `release/` contents.
- Inno Setup is available at
  `%LOCALAPPDATA%/Programs/Inno Setup 6/ISCC.exe`.
- This is an unsigned diagnostic candidate, not a formal release.

## CodeRabbit Integration

**Primary Type:** Deployment  
**Secondary Types:** Security, Architecture  
**Complexity:** High

- Primary: `@devops`; quality gate: `@architect`; supporting review: `@qa`.
- Pre-deployment review is candidate-bound and local; no publish operation is
  authorized.
- CodeRabbit falls back to manual review when the configured WSL runtime lacks
  `bash`.

## Change Log

| Date | Version | Description | Author |
|---|---:|---|---|
| 2026-08-10 | 0.1.0 | Initial isolated Windows V34 build story | Chronos (`@sm`) |
| 2026-08-10 | 0.1.1 | Validated GO (9.5/10) - Status: Draft to Ready | Themis (`@po`) |

## Dev Agent Record

### Agent Model Used

Not started.

### Debug Log References

Not started.

### Completion Notes List

Not started.

### File List

- `docs/stories/ONYX-REL-1.1.9-V34-WINDOWS-CANDIDATE.md`

## QA Results

Pending.
