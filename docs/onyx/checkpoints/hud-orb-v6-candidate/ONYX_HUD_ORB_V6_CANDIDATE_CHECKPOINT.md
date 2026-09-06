# Onyx HUD / Orb V6 Candidate Checkpoint

- Candidate: `ONYX-HUD-ORB-V6-CANDIDATE-003`
- Status: **default-off candidate; not live and not externally accepted**
- Opt-in: exact byte-for-byte `ONYX_HUD_V6_CANDIDATE=1`

## Outcome

The V6 candidate replaces only the visual QML source behind the accepted V5
runtime seam. It retains the V5 projection, command callbacks, camera path,
voice/mute state, autonomy, file drop, remote access, history, permissions,
software fallback, single `QQuickWidget`, 16-to-12 FPS governor and zero-FPS
minimized/hidden lifecycle.

No byte in `ui.py`, `main.py`, the V5 shell/Orb, accepted V3 projection/governor
or Activation V8 was changed for this candidate. Installation is reversible in
memory and restores the previous V5 host reference and flag value exactly.

## Visual result

The rectangular dashboard treatment was removed. The physical 1440x900 result
uses a dominant floating neural particle entity, deep black spatial field,
light typographic rails and a wide command deck. The Orb has no surrounding
frame, glass shell, corner bracket or closed card. A circular GPU mask removes
the black plate embedded in the source texture while preserving the exact
original asset SHA-256.

The new QML uses Cyryx Onyx/Obsidian/Graphite/Gunmetal, Steel/Silver, Core Teal
and Teal Glow tokens from Design System v1. Teal is limited to active-state
signals and restrained particle activation.

## Physical Windows evidence

Candidate 003 reuses the Candidate 002 PNG and physical metrics byte-for-byte.
No QML, asset, renderer or capture-evidence byte changed; Candidate 003 changes
only Python formatting, verifier identity and the documentary freeze boundary.

- Renderer: `GraphicsApi.Direct3D11Rhi`
- Resolution: 1440x900
- Active: 16 FPS, 0.4041% host CPU
- Settled idle: 0 FPS, 0.0418% host CPU
- Hidden: 0 FPS, 0.0139% host CPU
- RSS: 198.84 MiB
- Qt Quick widgets: exactly one, physically enumerated from
  `QApplication.allWidgets()` and validated as the expected host
- Screenshot: `onyx-hud-v6-d3d11.png`
- Screenshot SHA-256:
  `07e567524b7e30e4a2db74cf326f4fb50870e5ce1e907ad94e91aa8c97dfbfcf`

These measurements satisfy the requested active <=0.8% and idle/hidden
<=0.15% host CPU thresholds on the measured 28-logical-CPU Windows host.

## Boundary

This checkpoint does not activate Onyx, change a launcher, restart a service,
modify Activation V8 or grant external acceptance. Native macOS/Linux physical
rendering remains outside this Windows visual-candidate evidence.
