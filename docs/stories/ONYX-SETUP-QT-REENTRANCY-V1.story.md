---
executor: "@dev"
quality_gate: "@qa"
quality_gate_tools: [code_review, regression_test, packaged_runtime_smoke]
---

# Story ONYX-SETUP-QT-REENTRANCY-V1

**Status:** Done  
**Release successor:** Onyx `1.1.26` / Release Workflow V91

## Story

Prevent the installed Windows Onyx process from terminating when the owner
clicks `SETUP`, without changing the cinematic layout, humanoid, voice, setup
fields or setup behavior.

## Acceptance criteria

1. `SETUP` returns from the active QML mouse callback before creating QWidget
   controls over the QQuickWidget surface.
2. Repeated setup requests in the same event-loop turn create at most one
   overlay.
3. An already visible setup overlay is raised instead of recreated.
4. The existing setup panel, credential flow, owner name, voice selector,
   operating-system selection and DayOps entry point remain unchanged.
5. The installed executable remains running and displays the setup panel after
   a physical click on `SETUP`.
6. No QML, humanoid, audio or layout source changes.

## Evidence

- The original installed `1.1.25` failure was reproduced twice as Windows
  `Application Error` event 1000 in `Qt6Core.dll`, exception `0xc0000409`.
- A focused Qt/QML regression asserts deferred, coalesced setup creation and
  preservation of the owner window.
- Packaged-runtime physical verification is required after the V91 build and
  local upgrade installation.

## File list

- `ui.py`
- `core/version.py`
- `core/onyx_hud_current_acceptance_v44.py`
- `core/onyx_packaged_runtime_hud_contract_v13.py`
- `core/onyx_packaged_runtime_hud_contract_v13.manifest.json`
- `docs/onyx/acceptance/VE-HUD-CURRENT-V44-E6-001.manifest.json`
- `packaging/onyx.spec`
- `scripts/build_release.py`
- `scripts/generate_release_workflow_v91.py`
- `scripts/package_hygiene.py`
- `scripts/verify_release_workflow_v91.py`
- `tests/test_onyx_hud_v5_live_integration.py`
- `tests/test_onyx_hud_current_acceptance_v44.py`
- `tests/test_packaged_runtime_hud_contract_v13.py`
- `tests/test_release_workflow_transition_v91.py`
- `tests/fixtures/release_workflow_transition_v91.json`
