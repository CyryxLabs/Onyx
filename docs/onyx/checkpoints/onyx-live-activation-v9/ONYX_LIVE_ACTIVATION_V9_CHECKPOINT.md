# Onyx Live Activation V9 — Accepted Runtime and HUD Composition

Status: **CANDIDATE READY FOR INDEPENDENT GATE — NOT LIVE**

V9 is a default-off additive composition of exactly two externally accepted
artifacts:

- Onyx Live Activation V8 E6;
- Onyx HUD Orb V6 Candidate 003 E6.

No accepted V8, HUD V6, V7, V5, Phase5, `main.py`, or `ui.py` byte was
changed.

## Regression closed

Older source shortcuts and bootstrap environments can still select a legacy,
V7, or V8-only launcher. That makes Onyx appear to have reverted even when the
new HUD exists in the checkout.

V9 makes its source-checkout route unambiguous:

- an empty bootstrap environment is normalized to the exact V9 active state;
- the exact V8 environment is established together with
  `ONYX_LIVE_ACTIVATION_V9=1` and `ONYX_HUD_V6_CANDIDATE=1`;
- HUD V6 is installed before the single `MainWindow` is constructed;
- shortcut creation and successful first-run setup both write the canonical V9
  bootstrap route;
- legacy, V7, V8, partial, aliased, or ambiguous V9 activation combinations
  fail closed before host import.

## Windows shortcut contract

During an installed V9 execution, and only for an unfrozen Windows source
checkout, `MainWindow._create_desktop_shortcut` creates:

- link: active Windows Desktop `Onyx.lnk`;
- target: `.venv\Scripts\pythonw.exe`;
- argument: `scripts\bootstrap_onyx_live_v9.pyw`;
- working directory: the exact source root;
- icon: the existing Onyx icon selected by the accepted V8 host.

The Python executable, bootstrap, canonical launcher, and runtime manifest are
regular-file and SHA-256 bound. Symlinks, path escape, missing files, hash
drift, legacy launchers, and invalid COM quoting are rejected before a link is
written. Recreating the shortcut is idempotent and produces the same five-field
specification.

Packaged/frozen Windows behavior and macOS/Linux behavior delegate to the
accepted V8 implementation. No installer artifact was changed.

## Transaction and rollback

- Accepted V8 transactional seams: 24.
- V9 additive seams: HUD V6 host, V9 shortcut, setup shortcut persistence.
- Total installed V9 seams: 27.

Every V9 failpoint restores the exact installed V8 state. Normal V9 rollback
removes only the V9/HUD V6 additions, restores the accepted V8 shortcut/setup
methods, establishes the exact V8 control environment, and preserves unrelated
environment values. A separate test/termination helper can unwind V8 to the
original host.

## Reproduced evidence

- Focused V9 pytest: `11 passed`.
- Accepted V8 E6 verifier: pass.
- Accepted HUD V6 Candidate 003 E6 verifier: pass.
- Empty-environment bootstrap preflight: exact V9, V8 active, HUD V6 active.
- Network-blocked bootstrap preflight: pass with zero network calls.
- One `QQuickWidget`, one HUD V6 root, and HUD installation before
  `MainWindow`: pass.
- Simulated Windows COM quoting and two idempotent recreations: pass.
- Runtime manifest, path, Python executable, launcher, and bootstrap drift
  refusals: pass.
- Three V9 seam failpoints restore exact installed V8: pass.
- Ruff formatting/check and Python compilation: pass.
- Cumulative verifier: pass.

## Honest execution boundary

The Windows link tests use simulated COM. Bootstrap execution is limited to a
real fresh Python `--preflight-only` process; it does not open the physical UI,
microphone, Gemini, or any network connection.

V9 remains default-off. No live activation, restart, physical shortcut write,
provider call, credential change, network call, package mutation, or installer
change was performed.

## Candidate controls

- Desktop/source bootstrap: `scripts\bootstrap_onyx_live_v9.pyw`
- Canonical launcher: `scripts\launch_onyx_live_v9.pyw`
- Active control: `scripts\launch_onyx_live_v9_active.cmd`
- Exact V8 rollback control: `scripts\launch_onyx_live_v9_rollback.cmd`
- Cumulative verifier: `scripts\verify_onyx_live_activation_v9.py`

