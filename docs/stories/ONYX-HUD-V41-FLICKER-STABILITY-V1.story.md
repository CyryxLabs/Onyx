# Story ONYX-HUD-V41-FLICKER-STABILITY-V1 — Humanoid Render Stability

**Status:** Done
**Predecessor:** `ONYX-REL-1.1.11-PARITY-LIVE-SUCCESSOR-V1`
**Release authority:** New immutable successor over Release Workflow V76; V76/1.1.13 remains the installed rollback predecessor.

## Story

**As the** Cyryx Labs owner,  
**I want** the approved Onyx humanoid to render continuously without intermittent flashing,  
**so that** the living presence remains visually coherent during idle, pointer attention, listening and speaking.

## Immutable Boundaries

- Preserve the current Onyx layout, Cyryx Labs palette, humanoid anatomy, voice, command behavior and capabilities.
- Do not modify or rebind the accepted V40/V76 predecessor artifacts.
- Restrict implementation to render scheduling, WebGL/QML composition stability and the minimum successor/release authority needed to install the fix.
- Keep reduced-motion behavior, mouse/camera attention and offline local rendering intact.
- Treat static screenshots as insufficient evidence; temporal evidence must cover a frame sequence.

## Acceptance Criteria

1. A repeatable baseline probe records frame-to-frame luminance and blank-frame behavior for the installed 1.1.13 humanoid.
2. The Three.js scene has one authoritative animation scheduler; state, resize and attention updates cannot create concurrent forced renders or duplicate loops.
3. WebGL/QML composition uses a stable surface and handles visibility or WebGL context transitions without flashing the humanoid or exposing an empty transparent frame.
4. Automated temporal tests cover READY, LISTENING and SPEAKING plus pointer attention, and reject blank frames, full-scene luminance collapse or renderer reinitialization.
5. Layout geometry, palette constants, humanoid point-cloud source, voice pipeline and application capabilities remain unchanged.
6. A new immutable release successor packages and installs the correction with rollback evidence preserving the current installed tree and owner data.
7. The installed successor passes startup, text-command, graceful-exit and temporal humanoid stability checks; any external startup-policy blocker is reported separately and is not misrepresented as renderer certification.

## Tasks / Subtasks

- [x] **Slice 0 — Reproduce and isolate**
  - [x] Capture an installed multi-frame baseline and identify the failing render/compositor invariant.
- [x] **Slice 1 — Stabilize renderer**
  - [x] Implement a single coalesced frame scheduler and stable surface composition.
  - [x] Preserve attention, speech response and reduced-motion semantics.
- [x] **Slice 2 — Temporal regression coverage**
  - [x] Add deterministic renderer-contract tests.
  - [x] Add multi-frame visual metrics for READY, LISTENING and SPEAKING.
- [x] **Slice 3 — Successor package and install**
  - [x] Create the immutable release successor and bump the internal candidate version.
  - [x] Build, back up, install and prove installed-byte identity.
- [x] **Slice 4 — Installed verification**
  - [x] Run lifecycle and temporal stability checks on the installed executable.
  - [x] Reconcile evidence without changing unrelated capability status.

## Testing

- Focused Python/QML/HTML renderer-contract tests.
- Headless Chromium multi-frame capture with deterministic state transitions.
- Native installed-window frame sampling on Windows.
- Existing HUD acceptance, packaged-runtime, startup, command and shutdown regression tests.

## Dev Agent Record

### Agent Model Used

- Codex / AEXOS `@dev` (Vulcan)

### Debug Log References

- `evidence/live/humanoid-flicker-baseline-1.1.13-steady20/`
- `evidence/live/humanoid-flicker-fixed-v16-buffered-source-pointer45-desktop/`
- `evidence/live/humanoid-flicker-fixed-1.1.15-installed-focused-pointer60-desktop/`
- `evidence/live/onyx-1.1.15-install.log`

### Completion Notes List

- The V15 opaque WebEngine surface still dropped its compositor texture under aggressive pointer movement.
- V16 keeps Three.js as the live renderer, validates every presented silhouette, retains the last complete frame in a 2D presentation buffer and maintains double-buffered QML continuity behind the WebEngine surface.
- Source stress: 302 desktop frames over 45 seconds, zero collapses.
- Installed 1.1.15 stress: 407 unobscured desktop frames over 60 seconds, zero collapses; minimum luminance 11.5445 versus median 11.5932.
- The packaged native startup and isolated Windows install/smoke/uninstall gates passed. The full repository pytest runner remains affected by its pre-existing collection hang; focused tests were executed directly and passed.
- Existing startup `ControlPlanePathError` remains a separate policy issue and was not changed by this visual-only correction.

### File List

- `docs/stories/ONYX-HUD-V41-FLICKER-STABILITY-V1.story.md`
- `qml/web/onyx-humanoid-three-v3.html`
- `qml/components/OnyxHumanoidEntityV12.qml`
- `qml/OnyxLiveShellV15.qml`
- `core/onyx_hud_orb_v16.py`
- `core/onyx_hud_current_acceptance_v42.py`
- `docs/onyx/acceptance/VE-HUD-CURRENT-V42-E6-001.manifest.json`
- `core/onyx_packaged_runtime_hud_contract_v11.py`
- `core/onyx_packaged_runtime_hud_contract_v11.manifest.json`
- `scripts/generate_release_workflow_v78.py`
- `scripts/verify_release_workflow_v78.py`
- `tests/fixtures/release_workflow_transition_v78.json`
- `tests/test_humanoid_compositor_continuity_v1.py`
- `tests/test_onyx_hud_current_acceptance_v42.py`
- `tests/test_packaged_runtime_hud_contract_v11.py`
- `tests/test_release_workflow_transition_v78.py`
- `core/version.py`
- `ui.py`
- `main.py`
- `packaging/onyx.spec`
- `scripts/package_hygiene.py`
- `scripts/build_release.py`

## Change Log

| Date | Version | Description | Author |
|---|---:|---|---|
| 2026-09-02 | 0.1.0 | Created focused humanoid flicker-remediation successor with temporal evidence requirements. | Chronos (`@sm`) |
| 2026-09-02 | 1.0.0 | Implemented and installed 1.1.15 with validated Three.js presentation continuity; passed source and installed pointer stress. | Vulcan (`@dev`) |

## QA Results

Pass for the scoped visual defect. Installed 1.1.15 remained stable for 407 focused native desktop frames under continuous pointer stress, with no blank, partial or luminance-collapse frame detected. Package lifecycle smokes passed. Repository-wide pytest was not claimed because its existing collection hang persisted.
