# Story ONYX-REFERENCE-FUNCTIONAL-PARITY-V1 — Clean-room Functional Parity Closure

**Status:** Ready for Review — 35/35 source contracts and canonical relevant regression PASS; package, installed, device, OAuth/account, native-sandbox, and live-provider gates remain explicitly open
**Reference snapshot:** public documentation and file names at commit `d3238af8bd4203cc960e3c758f7d83440eef96f8`
**Predecessor:** `ONYX-MARK-LI-BROWNFIELD-GAPS-V1`

## Story

**As the** Cyryx Labs owner,  
**I want** every publicly documented reference capability represented by an original Onyx-owned capability contract,  
**so that** Onyx reaches auditable functional parity without importing third-party code, branding, license terms, prompts, tests, assets, or implementation details.

## Immutable Boundaries

- The product name remains **Onyx** and the vendor/owner remains **Cyryx Labs LLC**.
- The root Cyryx license remains authoritative. No third-party source or license is copied or relicensed.
- Reference inspection is limited to public README behavior, directory/file names, license classification, and commit metadata. Implementation files are not opened.
- The accepted V40 HUD composition, humanoid, palette, typography, controls, motion, Three.js/QML assets, voice identity, and layout are unchanged.
- A conversational call alias may be owner-configured, but it never changes product identity, vendor, legal notices, executable names, package IDs, UI branding, or evidence records.
- `implemented`, `host-integrated`, `tested`, `packaged`, `installed`, and `live-provider-verified` are separate states. No lower state may be reported as a higher one.

## Acceptance Criteria

1. A closed capability registry covers every feature listed in the reference README plus the currently visible calorie, repetition-counter, and video-upload action concepts. Every row names original Onyx evidence and independently reports source, host, test, package, installed, and live state.
2. Registry validation fails on duplicate/missing feature IDs, missing evidence files, foreign product branding in product code, or any attempt to report unavailable package/live evidence as verified.
3. Spoken-language memory detects supported language signals without storing transcripts, requires bounded confidence before persistence, supports inspect/manual override/revoke, and influences only response language. It cannot alter authority or voice identity.
4. Owner customization supports an optional conversational call alias through CLI/voice-safe backend contracts while immutable identity remains `Onyx by Cyryx Labs`. Reserved vendor/product identity cannot be replaced.
5. Social caption generation supports deterministic strategy planning and an optional explicitly authorized provider adapter. Provider use is separate from upload, accepts no secrets in prompts/results, and returns only a draft with provenance and validation warnings.
6. Existing governed video lease, preview, exact consent, one-dispatch, receipt, readback, and reconciliation contracts remain the only upload authority. No live connector is represented as active without OAuth/account/test-channel evidence.
7. Plugin parity remains brokered and fail-closed: discovery/lifecycle are host-integrated; execution cannot be called production-ready until a certified native sandbox adapter exists. This stricter boundary counts as a capability implementation, not a live activation.
8. Tests prove layout-source hashes/content remain unchanged, the Cyryx license remains authoritative, no reference implementation artifact is present, and all new behavior is default-safe.
9. A package candidate must include every newly host-imported runtime module before package parity can pass. Installed/live parity requires separate exact-artifact and provider/device evidence.

## Tasks / Subtasks

- [x] **Slice 0 — Parity registry and clean-room contract**
  - [x] Add the closed registry and a machine-readable CLI report.
  - [x] Bind all source evidence and preserve the Cyryx license/hash.
- [x] **Slice 1 — Silent language memory**
  - [x] Add bounded transcript-free detection, persistence, override, revoke, CLI, host observation, and prompt projection.
- [x] **Slice 2 — Governed conversational alias**
  - [x] Add immutable-identity profile, CLI, voice-safe parsing, host observation, and prompt projection without UI changes.
- [x] **Slice 3 — Strategic/provider caption drafts**
  - [x] Add platform strategy plans and optional provider generation with explicit network authorization and deterministic fallback.
- [x] **Slice 4 — Packaging and regression**
  - [x] Confirm static package discovery for the two `main.py`-imported identity modules; keep engineering CLIs source-only until an authorized release successor rather than breaking the sealed package spec.
  - [x] Run focused, canonical relevant, branding/license/provenance, and layout-freeze gates; preserve the two historical package/HUD blockers as open evidence rather than resealing them.
- [x] **Slice 5 — Truthful completion record**
  - [x] Mark source/host/test/package evidence exactly; leave installed/provider/device gates open unless physically proven.

## Testing

- Pure deterministic unit tests for language/alias/strategy contracts.
- Main-host characterization tests for transcript observation and prompt projection.
- Registry evidence and foreign-brand scan tests.
- Existing capability-expansion, social, voice, permission, package, and layout-freeze regressions.

## Dev Agent Record

### Agent Model Used

- Codex / AEXOS `@dev` (Vulcan)

### Debug Log References

- Ruff and `py_compile` passed on all new/modified Python surfaces.
- Focused new-contract gate: `14 passed`.
- Functional expansion gate without canonical preflight: `155 passed`; nine historical packaged-runtime fixture failures were isolated and not attributed to the new behavior.
- Canonical relevant gate with repository `conftest.py`: `266 passed, 230 subtests passed` in `209.52s`.
- Layout-freeze test passed. Direct historical V40 verifier still reports the pre-existing `ui.py` byte/newline drift; no UI/QML/Three.js/visual file was modified.
- Native package input test still reports a pre-existing missing/stale packaged-runtime V5 fixture path during isolated staging. No release authority was resealed.

### Completion Notes List

- Added transcript-free spoken-language memory with conservative automatic confirmation and owner override/revoke.
- Added an optional conversational alias while hard-locking product/vendor identity to Onyx/Cyryx Labs.
- Added deterministic platform strategy plans and an explicitly authorized optional Gemini draft boundary; drafts never upload or grant publication authority.
- Added a closed 35-row parity registry and JSON CLI. Source-contract coverage reports 100%; package, installed, and live-provider fields remain false.
- Preserved the accepted layout and voice identity. No visual source was edited.
- Root Cyryx license remained SHA-256 `E045278221225C8F0EF82A4332770B6ECB1DCC96BBEFC64E976C9CC15E8B7D95`.

### File List

- `docs/stories/ONYX-REFERENCE-FUNCTIONAL-PARITY-V1.story.md`
- `docs/onyx/ONYX_FUNCTIONAL_PARITY_V1.md`
- `docs/onyx/ONYX_CAPABILITY_EXPANSION_PROVENANCE_V1.md`
- `core/spoken_language_memory_v1.py`
- `core/assistant_identity_profile_v1.py`
- `core/social_content_strategy_v1.py`
- `core/capability_parity_v1.py`
- `scripts/onyx_identity_cli.py`
- `scripts/onyx_parity_cli.py`
- `scripts/onyx_social_cli.py`
- `main.py`
- `tests/test_spoken_language_memory_v1.py`
- `tests/test_assistant_identity_profile_v1.py`
- `tests/test_social_content_strategy_v1.py`
- `tests/test_capability_parity_v1.py`

## Change Log

| Date | Version | Description | Author |
|---|---:|---|---|
| 2026-09-01 | 0.1.0 | Created clean-room parity closure story from the owner-authorized public behavior inventory. | Chronos (`@sm`) |
| 2026-09-01 | 0.2.0 | Implemented and canonically tested 35/35 source-contract parity while preserving package/live evidence boundaries. | Vulcan (`@dev`) |

## QA Results — Current

### Reviewed By

Argus (`@qa`)

### Verdict

**PASS for source-contract/host/test review; NOT YET PACKAGED OR LIVE.**

- The 35-row registry is closed and all declared source/test files exist.
- Canonical relevant regression passed 266 tests and 230 subtests.
- New product code contains no foreign project/creator/license branding.
- Root product identity and Cyryx license remain authoritative.
- The visual freeze passed and no accepted UI asset was modified.
- Package/installed/live status remains false because no new exact release candidate, install smoke, native sandbox, OAuth/account test target, physical calibration, or live-provider readback was produced.
