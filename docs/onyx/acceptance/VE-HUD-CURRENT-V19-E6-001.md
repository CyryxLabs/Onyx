# Onyx Current HUD V19 Acceptance

Decision: accepted as the current production integrity and semantic authority.

The live root is `qml/OnyxLiveShellV9.qml`. Its QML inheritance and component
closure is V9 -> V8 -> V7, plus `OnyxOrbEntityV7` and
`OnyxOrbVoiceLayerV8`; the particle texture is also pinned as a runtime input.

The acceptance verifies exact SHA-256 bytes, an arc-free current surface,
twenty-two internal speaking rays, the forty-eight-bar speaking equalizer,
twelve-FPS governance, live audio-level reactivity, and Onyx/Cyryx Labs
branding with no legacy external franchise or predecessor-product text.

The earlier V7 and V8 manifests remain immutable historical evidence. They are
superseded for current-runtime semantics and are not rewritten or presented as
the V19 production HUD authority. The stale candidate suite
`tests/test_hud_orb_v8_c001_acceptance.py` is explicitly tombstoned from test
collection; `tests/test_onyx_hud_current_acceptance_v19.py` is its supported
PySide6 successor.

The executable acceptance test loads the real V9 QML scene through PySide6 in
software/offscreen mode and exercises speaking-to-idle behavior. No new
physical screenshot is claimed by this integrity record.
