# ONYX-REL-1.1.9-P0-QML-ACCESSIBILITY-STABILITY - Single-root HUD boot

## Status

**In Progress**

## Story

**As the** Onyx release owner,  
**I want** the authenticated current HUD to publish only its final QML root,  
**so that** normal voice transitions and later Windows accessibility/UI
inspection cannot traverse detached predecessor roots or terminate Qt.

## Acceptance Criteria

1. The rejected V39 receipts and WER evidence remain immutable.
2. The established V5-V10 authority chain remains authenticated and no
   arbitrary host/factory injection is accepted.
3. A current host allocates exactly one `QQuickWidget` and publishes exactly
   one QML source: `OnyxLiveShellV10.qml`.
4. No historical V5-V9 root is loaded and detached during V10 construction.
5. Focused HUD, packaged-runtime, startup and release regressions pass.
6. A traceable successor is built and survives repeated Windows UI Automation
   traversal after natural Gemini voice output.
7. The successor completes a fresh installed long-session receipt.

## Tasks / Subtasks

- [x] Preserve V39 failed long-session receipts and correlate both crashes to
  `Qt6Core.dll` fail-fast during post-voice UI Automation traversal.
- [x] Isolate the repeated predecessor `setSource()`/`setSource(QUrl())` chain.
- [x] Implement authenticated direct allocation from the original V5 owner.
- [x] Add source regression for one widget, one final QML publication and
  rejection of an untrusted MRO.
- [x] Bind the correction into the V41 HUD/source acceptance chain.
- [x] Run proportional source and packaged-runtime regression gates.
- [x] Freeze, build and install the traceable V41 successor; complete repeated
  accessibility traversal after provider output.
- [ ] Complete the active 28,800-second V41 installed long-session receipt.

## Failure Evidence

- V39 first failure: `ONYX_1_1_9_V39_WINDOWS_LONG_SESSION_RECEIPT.json`, after
  aggressive QML image capture.
- V39 second failure:
  `ONYX_1_1_9_V39_WINDOWS_LONG_SESSION_ATTEMPT3_RECEIPT.json`, immediately
  after a subsequent UIA tree traversal.
- Both WER records identify `Onyx.exe` 1.1.9, `Qt6Core.dll` 6.11.1,
  exception `0xc0000409`, subcode `7`, offset `0x1cf68`.
- Source Qt diagnostics reported detached QML roots and retained listeners from
  predecessor shells loaded and cleared during current-host construction.

## Dev Agent Record

### Agent Model Used

Codex

### Debug Log References

- `C:/MAAX_Assistant/Onyx-V41-Windows-Candidate-20260810.SOURCE_FREEZE.json`
- `docs/onyx/operations/ONYX_1_1_9_V41_WINDOWS_ACCEPTANCE_2026-08-10.md`
- `C:/MAAX_Assistant/Onyx-V41-Windows-Candidate-20260810/acceptance/installed-v41/ONYX_1_1_9_V41_WINDOWS_LONG_SESSION_RECEIPT.json`

### Completion Notes List

V39 remains rejected. V41 was built from the exact 2,661-file source freeze,
installed, and survived 32 repeated Windows UI Automation traversals with the
expected 25 descendants after provider output. No WER application error or Qt
termination was observed. The final criterion remains open until the active
28,800-second V41 receipt reaches a passing terminal state.

### File List

- `core/onyx_hud_orb_v10.py`
- `tests/test_onyx_hud_accessibility_stability_v1.py`
- `docs/stories/ONYX-REL-1.1.9-P0-QML-ACCESSIBILITY-STABILITY.md`
- `docs/onyx/operations/ONYX_1_1_9_V41_WINDOWS_ACCEPTANCE_2026-08-10.md`
- `docs/onyx/operations/ONYX_1_1_9_V41_SBOM_RECONCILIATION_2026-08-10.md`

## QA Results

V41 successor regression is accepted within the observed Windows installed
scope. Long-session closure and formal release review remain pending.
