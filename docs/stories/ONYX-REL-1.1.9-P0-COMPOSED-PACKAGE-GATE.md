# ONYX-REL-1.1.9-P0-COMPOSED-PACKAGE-GATE - Final Bundle HUD Closure

## Status

**In Progress**

## Story

**As the** Onyx release owner,  
**I want** the authenticated HUD contract to validate the composed final bundle,  
**so that** separately valid runtime-source and runtime-document stages cannot
produce an executable that fails its first packaged smoke.

## Acceptance Criteria

1. The failed V34 candidate and its source-freeze manifest remain immutable
   evidence; the fix is made only in the authoritative source checkout.
2. The V19 HUD acceptance manifest, required by the shipped V19 verifier and
   runtime-document closure, is explicitly admitted and SHA-256-bound.
3. Every member of every exact packaged HUD set is individually SHA-256-bound.
4. A regression test composes runtime sources, runtime documents, `main.py`, and
   `ui.py` at one resource root and passes the frozen contract.
5. Package, portable, Windows-regression, V41 successor and release-workflow
   gates pass before a new source snapshot is frozen.
6. A new successor receipt supersedes V41/V34 without rewriting either
   historical receipt.

## Tasks / Subtasks

- [x] Preserve and diagnose the failed V34 build evidence.
- [x] Correct the exact-set authority and deterministic generator.
- [x] Add composed-root and complete hash-binding regression tests.
- [x] Generate and verify authenticated V35 successor.
- [x] Run focused and broad quality gates for the composed package correction.
- [ ] Freeze and build a new isolated Windows candidate.

## Failure Evidence

- Source freeze: `Onyx-V34-Windows-Candidate-20260810.SOURCE_FREEZE.json`
- Frozen root: `ce9e0883ab082afcdde286b778f1286aee045372db12e235a2f3ee8f54dd20a4`
- Build reached the first packaged executable smoke and exited `70`.
- Diagnostic log: `build/smoke-data/runtime/logs/onyx-bootstrap-diagnostic.log`
- Root cause: `VE-HUD-CURRENT-V19-E6-001.manifest.json` was intentionally
  staged by runtime docs but omitted from the compiled exact-set authority.

## Dev Agent Record

### Agent Model Used

Codex

### Debug Log References

- V34 source freeze verified: 2,611 files; 139,609,401 bytes.
- Candidate tests before build: 43 passed.
- PyInstaller bundle completed; packaged smoke failed closed before installer.
- V35 freeze completed: 2,617 files; 139,631,151 bytes; aggregate root
  `2f192a7a8a7945082803ca22aedea12574e0c7f45168aa89cdec501b0274795c`.
- V35 passed the composed package fallback and V24 preflight gates, proving the
  V19-V25 manifest correction. Its next smoke failed because startup eagerly
  discovered an ambient Claude CLI and attempted `claude --version` inside the
  provider-free subprocess fence. V35 remains immutable failed evidence.
- Remediation continues in
  `ONYX-REL-1.1.9-P0-LAZY-EXTERNAL-AGENT-STARTUP.md`; a V36 source freeze is
  required.

### Completion Notes List

The composed package closure is source-verified. Final completion remains
pending a replacement build that passes the native startup smoke.

### File List

- `core/onyx_packaged_runtime_hud_contract_v1.py`
- `scripts/generate_hud_v26_manifests.py`
- `tests/test_packaged_runtime_hud_contract_v1.py`
- `scripts/generate_release_workflow_v35.py`
- `scripts/verify_release_workflow_v35.py`
- `tests/fixtures/release_workflow_transition_v35.json`
- `tests/test_release_workflow_transition_v35.py`
- `docs/onyx/checkpoints/RELEASE_WORKFLOW_V35_VERIFIER_RECEIPT.json`
- `docs/stories/ONYX-REL-1.1.9-P0-COMPOSED-PACKAGE-GATE.md`

## QA Results

Pending.
