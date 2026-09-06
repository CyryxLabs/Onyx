# Onyx HUD / Orb V2 Checkpoint

Date: 2026-07-22

Status: implementation candidate, isolated and default-off. This checkpoint
does not replace the current UI, restart Onyx, or wire the candidate into
`main.py`, `ui.py`, `dashboard/server.py`, or `core/permission_broker.py`.

## Visual contract

- Introduces a full Cyryx Labs shell using only Onyx, Obsidian, Graphite,
  Gunmetal, Steel, Silver, Core Teal, Teal Glow, and transparent derivatives.
- Uses dark neutral material as the visual mass. Teal is a minority energy and
  focus signal rather than the Orb body or a page background.
- Renders one procedural Obsidian/Silver presence with volumetric lighting,
  depth-sorted matter, sparse teal energy nodes, restrained filaments, surface
  caustics, atmospheric bloom, and state-dependent energy.
- Contains no corner markers, acquisition brackets, crosshairs, octagonal
  cages, solid teal sphere, external image, external texture, external shader,
  or third-party visual asset.
- Replaces the old center-column composition with a responsive presence rail,
  entity stage, active-context rail, and rounded command dock while retaining
  command, mute, settings, history, permissions, close, lifecycle, transcript,
  identity, state, and audio projection contracts.

## Render policy

- Static idle after a 650 ms transition settle; no recurring idle timer.
- Explicit 12 / 24 / 30 FPS tiers only.
- Hidden, minimized, muted, offline, and reduced-motion states stop animation.
- Three consecutive slow frames downgrade the adaptive cap. Upgrade requires
  a long healthy streak and a five-second cooldown to prevent oscillation.
- Visual audio samples are accepted at no more than 20 Hz.
- A single Canvas renderer draws at most 160 deterministic points. There are
  no per-particle Qt Quick 3D meshes and no sphere-mesh farm.
- The governor owns no thread and no timer. The QML host owns one coarse frame
  clock that stops when `animationRunning` becomes false.

## Verification snapshot

- New V2 tests plus current Orb, lifecycle, performance, and packaging
  regressions: `34 passed`.
- Python bytecode compilation: passed.
- Ruff over the new Python implementation and tests: passed.
- `QQmlComponent` creation: passed for both the shell and Orb.
- Public `QQuickView` + `QQmlContext.setContextProperty` load path: `Ready`.
- 20,000 governor snapshots: p50 `0.002900 ms`, p95 `0.005000 ms`, maximum
  `1.734200 ms` on this Windows software test host.
- 20,000 adaptive `report_frame` calls: `27.511 ms` total.
- A 1440 x 900 software/offscreen frame was rendered successfully for
  geometry and palette inspection.
- Static source checks prove one V2 renderer, a 160-node hard ceiling, approved
  opaque brand colors only, no external URL/file/shader dependency, recursive
  QML packaging coverage, and no V2 reference from the four live surfaces.

## Frozen candidate hashes

- `core/render_governor.py`:
  `923b659373d6194749ab5e9e803b6b0cd995f82c5410528cacea2d6fa2188461`
- `core/ui_projection.py`:
  `b5bce8a27271ab0306fb21e61f3d90738490b946d987606ee104b2018d44cb19`
- `qml/OnyxShell.qml`:
  `6fc614464c3015d724b11a5647a33fe0de5d980343451fc72dba27cb7e8ec98a`
- `qml/components/OnyxOrbV2.qml`:
  `78fac811adb07de99f1e95baae94956ba41b189890224877a2441f0365e21311`
- `qml/components/HoloPanel.qml`:
  `72959332c71b1dad12656e881177d0f75f4d8f4f9be41036cb5628a945e9cfcd`
- `qml/components/StatusPill.qml`:
  `2637d1dd4cf3ab61d510c90a055d9063419c7dd05dc6275fb368a8dc6f64d038`
- `qml/components/TelemetryBar.qml`:
  `d19be61a5e99145fb80afbf6fb6810cfad58bfce8720ca28357d5a30e51e3ff5`
- `tests/test_render_governor.py`:
  `6ffc50f38cd5b7be1fe38d927c3599828b6d2ca0190f048a635baada11a338db`
- `tests/test_onyx_hud_v2.py`:
  `f469ea701d1beacde24432e78373e864d75de4d75c881edc9e8a65e36c1332b8`

## Honest limitations

- This is an isolated candidate. The owner cannot see it in the current Onyx
  window until a separately reviewed integration switches the live host to
  `OnyxShell.qml` and connects lifecycle events.
- The Orb is a bounded procedural 2.5D Canvas entity, not a ray-traced scene.
  This is intentional for CPU discipline and broad Qt/platform compatibility.
- The software governor cost is measured; real GPU/driver usage, idle CPU/RSS
  deltas, and visual motion quality still require physical Windows testing.
- The offscreen Qt platform on this host reports zero installed font families.
  Geometry, palette and QML loading were verifiable, but final typography must
  be checked through the real Windows platform plugin. The QML uses public
  system-font fallbacks for Windows, macOS, and Linux.
- macOS and Linux QML loading remains source-covered only until executed on
  those native hosts.
- External functional, integrity, visual-quality, and performance review is
  still required before live activation.

Bundle root:
`docs/onyx/checkpoints/hud-orb-v2/`

Machine-readable manifest:
`docs/onyx/checkpoints/hud-orb-v2/manifest.json`
