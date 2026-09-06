# Onyx HUD / Orb V3 Checkpoint

Date: 2026-07-22

Status: corrected implementation candidate, isolated and default-off. V3 does
not replace the current UI, restart Onyx, or wire into `main.py`, `ui.py`,
`dashboard/server.py`, or `core/permission_broker.py`.

HUD / Orb V2 remains a rejected historical candidate. Its nine manifest files,
manifest and checkpoint are byte-exact. V3 adds only versioned files and uses
the frozen V2 visual/governor implementation as an explicit dependency.

## Corrected findings

### P1 - reachable mute and close controls

- The V3 shell exposes visible rounded `MUTE` / `UNMUTE` and `CLOSE` actions in
  the top command surface.
- Each control has a minimum 34 px height, visible focus treatment, tab focus,
  Enter, Return and Space activation, pointer activation, an accessibility
  Button role, name, description, and accessibility press action.
- The controls call only the existing `requestMuteToggle()` and
  `requestClose()` projection contracts. No new authority path is introduced.
- Real QQuickView keyboard tests prove Space invokes mute with the requested
  boolean and Return invokes close.

### P2 - explicit command acceptance

- `submitCommand()` now succeeds only when a configured callback exists,
  completes without exception, and returns the singleton boolean `True`.
- Missing callback, exception, `False`, `None`, integer `1`, and other
  non-`True` results return `False` and preserve the command input.
- `commandRequested` is emitted only after explicit callback acceptance, so a
  rejected command cannot escape through the projection signal.
- Failures expose bounded statuses (`COMMAND UNAVAILABLE`, `COMMAND FAILED`,
  `COMMAND REJECTED`) and sanitized error codes without exception messages.
- Success exposes `COMMAND ACCEPTED`, clears prior error state, emits the
  accepted-command signal, and only then lets QML clear the input.
- The V3 command field and RUN action are tab-focusable, keyboard operable, and
  expose public Qt accessibility metadata.

## Preserved visual and render contract

- The V2 Obsidian/Silver procedural entity and Cyryx Labs palette are reused
  byte-for-byte; teal remains a minority energy signal.
- No solid teal body, sphere mesh, corner marker, acquisition bracket,
  crosshair, octagonal cage, external asset, external URL or shader is added.
- One renderer, a 160-node ceiling, static idle after settle, 12/24/30 FPS,
  hidden/minimized stop, audio updates at no more than 20 Hz, and adaptive
  downgrade/upgrade hysteresis remain unchanged.
- The corrected command surface fully covers the clipped historical command
  surface, while the presence rails, entity stage and current actions remain
  intact.

## Verification snapshot

- V3 adversarial tests plus V2/current Orb, lifecycle, performance and
  packaging regressions: `51 passed`.
- Python bytecode compilation: passed.
- Ruff over V3 Python and tests: passed.
- QQuickView/QML load: `Ready`, zero errors.
- Real offscreen keyboard/focus tests: passed for command Enter, mute Space and
  close Return.
- Input-retention tests: passed for missing callback and callback `False`;
  input-clear test passed only for callback `True`.
- V2 byte preservation: nine of nine manifest files, manifest and checkpoint
  hashes passed.
- 20,000 V3 governor snapshots: p50 `0.003200 ms`, p95 `0.003700 ms`, maximum
  `2.950900 ms` on this Windows software host.
- 10,000 explicitly accepted command projections: p50 `0.004000 ms`, p95
  `0.004500 ms`, maximum `4.313400 ms`.
- A 1440 x 900 software/offscreen V3 frame rendered successfully with zero QML
  errors for geometry, action reachability, overlay and palette inspection.

## Frozen V3 hashes

- `core/render_governor_v3.py`:
  `ee1f2145eb90e930e1663287bc0e71ff6f0809b9b4bce18e445c2f47e80d1de8`
- `core/ui_projection_v3.py`:
  `cfbcc566dbcb5bd423b31571ef914bb24f389621c781d1edf05a02fd0792b7d2`
- `qml/OnyxShellV3.qml`:
  `4f450c9ff7b2a9926925273a29fb8cc77533576073f2015be3f87b450c180eac`
- `qml/components/ActionButtonV3.qml`:
  `a30e45dea796faa9a3ccf69ccb99085106a0de1f019d43c0b12125a35052f4eb`
- `tests/test_render_governor_v3.py`:
  `15704af20c1859d1b61b3a30c645dcc26b625fce49b0fd581ff993830023a3e4`
- `tests/test_onyx_hud_v3.py`:
  `928e92c25be8218ef83d2dbf035330c0017eef9bb03bfd2a737cbb82e39b5b9f`

## Honest limitations

- V3 is not live-wired. Its actions cannot be used in the current Onyx window
  until a separately reviewed integration selects `OnyxShellV3.qml` and
  supplies `OnyxUIProjectionV3` callbacks/lifecycle.
- V3 intentionally depends on byte-frozen V2 visual components and governor;
  the V2 bundle remains rejected, while its two rejected interaction seams are
  overridden and adversarially tested by V3.
- The Orb remains a bounded procedural 2.5D Canvas entity rather than a
  ray-traced renderer. This preserves the CPU and portability design.
- Physical Windows GPU/driver use, idle CPU/RSS delta and real-platform
  typography/motion quality remain pending.
- Native macOS and Linux execution remains pending.
- External functional, integrity, accessibility, visual-quality and
  performance review remains required before live activation.

Bundle root:
`docs/onyx/checkpoints/hud-orb-v3/`

Machine-readable manifest:
`docs/onyx/checkpoints/hud-orb-v3/manifest.json`
