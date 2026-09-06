# Voice Session Authority V1 — E6 acceptance

- Evidence ID: `VE-VOICE-SESSION-AUTHORITY-V1-E6-001`
- Decision date: `2026-08-19`
- Decision: **ACCEPTED — default-off voice-opened bounded session authority**
- Candidate manifest: `docs/onyx/checkpoints/voice-session-authority-v1/manifest.json`
- Artifact root: `8d16f979db21395e3c3ba8896ca8e8442b2ecedfe548c1ebfb75a88faaf6e7aa`

Final findings are `P0=0`, `P1=0`, `P2=0` and `P3=0`. This is the exact
low-risk enablement slice the capability matrix names as the next step for
bounded session grants, and the **first Onyx contract that grants authority
rather than shadowing it**. `core/voice_session_authority_v1.py`
(`ONYX_VOICE_SESSION_AUTHORITY_V1`, default-off, deterministic, hermetic,
injected clock) is designed to install as the permission broker's
`governance_authorization_hook`, consulted before the trusted-host prompt.

It enforces, structurally: the kill switch denies ahead of every other rule,
closes the open envelope and blocks reopening; `ALWAYS_EXPLICIT` pairs defer
unconditionally, including `file_controller.delete` inside an authorized
root and every action of `browser_control`, `computer_control`,
`desktop_control`, `computer_settings`, `send_message`, `dev_agent` and
`game_updater`; every path argument across nine keys must resolve inside an
authorized root, compared by whole path components so `C:\Work2` never
passes as inside `C:\Work`, with traversal, relative and unusable values
deferring; envelopes are bounded at construction (lifetime one minute to
eight hours, cap one to ten thousand) and return to asking on expiry or cap
exhaustion; opening requires an exact trigger phrase of at least three
words; and `None` is the default answer, so anything unrecognised keeps the
existing approval behaviour unchanged. The module calls no model, opens no
network, spawns no process, persists nothing and reads no clock. The gate
reproduced **977 passed tests and 96 passed subtests, 0 failed and 0
errors** across thirty-five fresh Python processes (seventeen explained
platform-specific skips).

Verification passes executed (2026-08-19, fresh processes): integrity —
artifact root `8d16f979` and all eight candidate artifacts recompute exactly
and the predecessor entry-bind is genuine; functional — trigger
unambiguity, envelope bounds, root containment including the sibling-prefix
case, the always-explicit set, expiry, cap exhaustion, kill-switch
precedence and the broker-hook adapter are enforced and adversarially tested
(67 tests); quality — the verifier itself opens a probe envelope and
machine-asserts that deletion, browser, desktop and messaging still defer,
that a sibling-prefix root is refused, that an in-scope in-root operation is
actually granted, that the kill switch denies, that the lifetime ceiling
holds and that `file_controller.delete` has not left the always-explicit
set; it also forbids network, process and clock-reading tokens.

**Owner decisions recorded (2026-08-19).** Shown in the choice itself that
Onyx has no speaker verification and that any audio near the microphone
produces an indistinguishable transcript, the owner chose voice-alone
opening with no confirmation step, and a scope of read + write + local
development over the authorized roots. This acceptance implements exactly
those decisions.

**Accepted exposure, recorded not hidden.** Without speaker verification, a
spoofed or accidental transcript carrying the trigger phrase can open an
envelope with write and local-execution authority over the authorized
roots. The mitigations bound the blast radius — exact multi-word phrase,
bounded lifetime and operation cap, whole-component root containment, the
always-explicit set and the kill switch — they do **not** prevent a spoofed
opening. Adding speaker verification would change this and is later,
separately reviewed work.

**Honesty boundary.** All verification passes were executed autonomously in
the owner-authorized session (@devops). No independent human review
occurred. Scope is the decision contract only: this acceptance installs no
hook, adds no runtime wiring, no UI envelope indicator and no persistence
across restarts, and does not claim the full Onyx PRD is complete.
