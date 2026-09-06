# HUD / Orb V7 Candidate 003 checkpoint

V7 Candidate 003 is the default-off cinematic visual successor to the
technically accepted but visually rejected V6 composition and the sparse-radar
V7 Candidate 001. Candidate 002 established the approved neural-sphere
baseline but was superseded, never live, by the owner's request to remove all
external orbit tracks. C003 preserves the accepted V6 host, projection,
one-QQuickWidget lifecycle and every existing interaction.

The physical 1440x900 D3D11 capture was reviewed and approved after iteration.
It presents a full-bleed holographic entity with a dominant approximately
600-pixel neural sphere, thousands of visible particles and connections,
circular masking, volumetric halo and luminous core. Decorative arcs, circles
and orbit tracks outside the sphere mask are absent; only the sphere's natural
luminous boundary, internal neural mesh and core remain. The former structural
inner ring is also absent. Asymmetric floating telemetry and the curved lower
command keel remain. It has no side-card rails, corner brackets, rigid panels,
QtQuick3D or WebGL.

The exact opt-in is `ONYX_HUD_V7_LIVE=1`; all other values are off. V7 requires
the hash-authenticated accepted V6 artifacts and the exact installed V6 host.
Rollback state is held in a private immutable record instead of the mutable UI
marker, so marker/host/flag drift cannot substitute the restoration target.
Runtime V9, V10 and shortcuts are unchanged.

Measured host CPU: active 0.585%, idle 0.096%, hidden 0.042%. Projection target
is at most 16 FPS; the visual timer is capped at 12 FPS and is stopped at idle
and hidden, where projection target is zero. Measurements are a single local
Windows D3D11 sample and do not establish cross-device performance.

The screenshot is physical evidence of this machine/configuration only.
Accessibility, keyboard input and responsive structure are present, but no
macOS/Linux physical render or user study is claimed. Candidate is not live.
