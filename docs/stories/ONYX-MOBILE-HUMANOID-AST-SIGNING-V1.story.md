# Story ONYX-MOBILE-HUMANOID-AST-SIGNING-V1 — Mobile Humanoid Parity and Release Truth

**Status:** In Progress
**Predecessor:** `ONYX-STARTUP-ATTENTION-REMEDIATION-V1`
**Release authority:** Local immutable successor over V80/1.1.17. Public distribution remains fail-closed unless Authenticode is verified as valid.

## Story

**As the** Cyryx Labs owner,  
**I want** the remote/mobile Onyx surface to carry the same living humanoid identity and operational composition as desktop, while its Gemini and signing checks reflect the real runtime,  
**so that** mobile use is visually coherent and release claims remain technically true.

## Immutable Boundaries

- Preserve the accepted desktop QML layout, Three.js humanoid source, Cyryx Labs palette, voice pipeline, command behavior and capabilities.
- Reuse the authoritative humanoid renderer; do not substitute a static image, orb or divergent mobile illustration.
- Keep remote authentication, AES command transport, WebSocket tickets, file transfer and microphone behavior intact.
- Do not weaken Authenticode requirements or classify an unsigned package as public/formal.
- Do not claim a signed public release without a valid trusted publisher certificate and verification receipt.

## Acceptance Criteria

1. The Gemini AST regression accepts the current payload-built `LiveConnectConfig` only when `system_instruction` is demonstrably present in the expanded payload.
2. The remote dashboard serves the same local Three.js humanoid renderer and assets used by desktop, without a static-image fallback.
3. Desktop-width remote composition mirrors the desktop hierarchy: brand/status header, left owner context, central living humanoid, right runtime state, conversation trace and command dock.
4. At 390×844 the composition remains usable without horizontal overflow, keeps the humanoid visible, preserves 44px controls and keeps command/mic/file actions reachable.
5. Humanoid READY/LISTENING/SPEAKING state and pointer/touch attention are driven from the mobile dashboard without duplicate animation loops or renderer reinitialization.
6. Existing remote login, command, AES, WebSocket-ticket, upload and phone-audio contracts remain passing.
7. Signing preflight reports the exact Authenticode readiness state and blocks formal/public qualification when no valid code-signing identity is available.
8. A local successor may be packaged and installed only after focused AST, dashboard, renderer, responsive, security and lifecycle checks pass.

## Tasks / Subtasks

- [x] **Slice 0 — Reproduce and authorize**
  - [x] Reproduce the historical AST failure independently of the repository collection hook.
  - [x] Confirm the current mobile dashboard lacks the humanoid renderer.
- [x] **Slice 1 — Correct contracts**
  - [x] Preserve the immutable historical AST assertion and add a current successor characterization around payload-built Gemini configuration.
  - [x] Add explicit Authenticode availability/qualification evidence without weakening public gates.
- [x] **Slice 2 — Mobile visual parity**
  - [x] Serve the authoritative Three.js humanoid assets through bounded local routes.
  - [x] Recompose the remote dashboard for desktop/mobile visual parity.
  - [x] Bind state plus pointer/touch attention to the humanoid.
- [x] **Slice 3 — Regression and browser QA**
  - [x] Add static/security/responsive renderer contracts.
  - [x] Verify 390×844, console, overflow and renderer readiness.
- [ ] **Slice 4 — Successor qualification**
  - [ ] Run focused and release gates.
  - [ ] Package/install a local successor if all local gates pass; retain unsigned-candidate status unless Authenticode is valid.

## Testing

- Isolated Gemini compatibility AST test plus live-config unit tests.
- Dashboard server route/auth/security tests and existing browser audio tests.
- Browser QA at 390×844 and desktop widths with renderer readiness, console and overflow assertions.
- Release signing preflight and focused package/lifecycle tests.

## Dev Agent Record

### Agent Model Used

- Codex / AEXOS `@dev` (Vulcan)

### File List

- `docs/stories/ONYX-MOBILE-HUMANOID-AST-SIGNING-V1.story.md`
- `core/version.py`
- `dashboard/server.py`
- `dashboard/static/app.html`
- `packaging/onyx.spec`
- `scripts/generate_release_workflow_v81.py`
- `scripts/verify_release_workflow_v81.py`
- `tests/conftest.py`
- `tests/fixtures/release_workflow_transition_v81.json`
- `tests/test_mobile_humanoid_parity_v1.py`
- `tests/test_release_workflow_transition_v81.py`

## Change Log

| Date | Version | Description | Author |
|---|---:|---|---|
| 2026-09-02 | 0.1.0 | Created focused AST, mobile humanoid parity and signing-truth successor. | Chronos (`@sm`) |
| 2026-09-02 | 0.2.0 | Added mobile Three.js parity, CSP correction, current-test successors and V81 release authority. | Vulcan (`@dev`) |

## QA Results

- Focused AST/dashboard/HUD/signing suites: 53 passed.
- Browser 390×844: 390px scroll width, 844px scroll height, no overflow, 304px humanoid frame, `THREE.JS / HUMANOID ONLINE`, connection `Connected`.
- Authenticode preflight: Windows SDK `signtool.exe` found; two private-key code-signing certificates found, both `CN=Petruff Technologies`, self-signed and rejected by the trust chain as `UntrustedRoot`. No certificate satisfies the public Cyryx Labs publisher gate; public/formal release remains blocked by design.
