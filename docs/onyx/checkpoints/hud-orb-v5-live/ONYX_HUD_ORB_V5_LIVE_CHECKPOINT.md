# Onyx HUD / Orb V5 Live Integration — Candidate 003

Status: **default-off isolated candidate**  
Activation flag: `ONYX_HUD_V5_LIVE=1` (exact value only)  
Fallback: the legacy Orb is forced to software only while Candidate 003 is requested, preserving one Qt Quick renderer.

## Semantic correction

- With Candidate 003 absent, `MainWindow` passes `force_fallback=None` to `OrbHost`. `ONYX_ORB_RENDERER=software` remains authoritative, while `auto` and `gpu` retain the legacy GPU-selection attempt and `ONYX_ORB_QUALITY` continues to flow through `OrbStateBridge`.
- With Candidate 003 requested, `MainWindow` passes `force_fallback=True` to the retained legacy Orb before constructing the sole V5 `QQuickWidget`.
- Minimize and restore events resynchronize the selected renderer. Software animation stops while minimized and resumes only for active cognition; V5 projection animation drops to zero while minimized and restores its 16 FPS active target afterward.
- The long-lived V5 host preserves Candidate 002's safe source-swap lifecycle, signal disconnection, one scene graph, 16-to-12 FPS governor, transparent additive Canvas, and complete control/public-API projection.

## Rejected candidate preservation

- Candidate 002 has no live activation flag in `ui.py` and is explicitly marked rejected.
- Its 13-file evidence set is preserved byte-for-byte in `candidate-002-snapshot/` (2,095,770 bytes).
- Frozen Candidate 002 manifest SHA-256: `8daf7a43fd08ee6d7548992f4a8ef2da48c4271142dabae4e8fb0ee76c50d495`.
- Frozen Candidate 002 checkpoint SHA-256: `42148552f863791979812f19b1019921ce9b785153f511f80803e40d127126d5`.

## Visual and physical evidence

- Candidate 003 changes only V4-to-V5 identifiers in the two QML visual files. A regression normalizes those identifiers and proves both QML files byte-identical to the frozen Candidate 002 visuals; the Orb asset is also byte-identical.
- Because no visual-affecting QML bytes changed, no new screenshot is represented as a new capture. The frozen physical Windows/D3D11 1440x900 screenshot is inherited honestly and bound by SHA-256 `03b99d56a542d48680c5baa42ffd818e20c6e87043dc82333d098be662ee57a1`.
- A fresh Candidate 003 physical D3D11 runtime measurement reported `GraphicsApi.Direct3D11Rhi`: active **0.5286% host CPU**, settled idle **0.0750%**, hidden **0.0679%** on 28 logical CPUs. Targets remain active <=0.8%, idle/hidden <=0.15%.

## Verification evidence

- Candidate 003 transition/integrity suite: **19 passed in 15.71s**.
- Representative HUD/governor/Orb/packaging/dashboard matrix including current `test_orb_3d.py`: **65 passed in 104.72s**.
- Fresh-process V5 stress: 4 windows x 30 live/legacy/live transitions, same `QQuickWidget`, clean exit, no `0xC0000005`.
- Python compile, Ruff runtime-critical rules (`F,E9`), full integration-module Ruff, and assigned-surface `git diff --check`: PASS before final manifest freeze.

## Isolated obsolete V2 result

`tests/test_onyx_hud_v2.py` was run separately: **6 passed, 2 failed**. Both failures are obsolete historical assertions: one prohibits every `Image` in all QML components, and the other prohibits any `OnyxUIProjection` integration in `ui.py`. Those contracts conflict with the accepted V3+ architecture and are documented rather than excluded from a claimed pass.

## Validation boundary

- No Onyx process was restarted, no service was changed, and Candidate 003 remains default-off.
- Physical renderer/runtime evidence is Windows/D3D11-specific. macOS and Linux native runtime/package validation remains outside this checkpoint.

`manifest.json` is the authoritative Candidate 003 byte manifest.
