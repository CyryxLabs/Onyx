# HUD / Orb V8 voice-reactive candidate checkpoint

V8 is a default-off, additive visual successor to the accepted HUD V7 C003.
It preserves the complete V7 composition, its one-QQuickWidget lifecycle,
projection, controls, Cyryx Labs palette and the approved Orb without external
orbit tracks. It adds one transparent particle layer clipped inside the
existing sphere.

The layer runs only while the projected operational state is `SPEAKING`.
Its timer is capped at 12 FPS, resets its phase to zero when speaking stops,
and remains stopped while listening, hidden, minimized, muted or under reduced
motion. It creates no thread, renderer, additional QQuickWidget, external arc,
ring, orbit or square geometry.

Two physical 1440x900 D3D11 speaking captures show the internal points in
different positions. A third physical capture shows the settled listening
state. The measured internal phase advanced from 0.34 to 1.105 while speaking,
then remained exactly 0.0 across two idle observations. The voice layer
reported 12 FPS while speaking and 0 FPS while idle and hidden.

Measured host CPU was 0.404% while speaking, 0.083% while idle and 0.000% while
hidden. These are single local Windows samples, not cross-device guarantees.

The exact opt-in is `ONYX_HUD_V8_LIVE=1`; every other value is off. The
candidate hash-authenticates the accepted V7 module and manifest, requires its
real immutable installation record, and rolls back exactly to that installed
V7 host. V10 and both user shortcuts remain unchanged at this checkpoint.

