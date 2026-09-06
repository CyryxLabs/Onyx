# Onyx Live Activation V8 — Shortcut Regression Candidate

Status: **CANDIDATE READY FOR INDEPENDENT GATE — NOT LIVE**

V8 is an additive correction over the externally accepted, default-off V7
candidate. No V1–V7, `main.py`, `ui.py`, HUD, Phase5, packaging, or installer
byte was changed.

## Confirmed regression

The frozen `ui.py` source-checkout shortcut creates `Onyx.lnk` with
`scripts/launch_onyx.pyw`. Therefore, recreating the shortcut while a live
activation candidate is running silently restores the legacy entrypoint.

Pointing the link directly at `launch_onyx_live_v8.pyw` would not solve the
regression: the canonical launcher intentionally treats an empty activation
environment as legacy. V8 therefore uses a dedicated, manifest-bound bootstrap.

## V8 shortcut contract

During an installed V8 execution, and only for an unfrozen Windows source
checkout, `MainWindow._create_desktop_shortcut` creates:

- link: active Windows Desktop `Onyx.lnk`;
- target: source checkout `.venv\Scripts\pythonw.exe`;
- argument: `scripts\bootstrap_onyx_live_v8.pyw`;
- working directory: source checkout root;
- icon: the existing `config\onyx.ico`.

The bootstrap removes stale V1–V8 activation/rollback controls and Phase5
identity aliases, preserves unrelated environment values, establishes the
complete exact V8 active environment, and invokes the canonical
`launch_onyx_live_v8.pyw`. It does not make an empty canonical-launcher
environment active.

The source-checkout shortcut fails closed before link creation unless the
target `.venv\Scripts\pythonw.exe`, bootstrap, and canonical launcher are all
regular files.

Packaged Windows, macOS, and Linux behavior delegates to the frozen
implementation without replacement. The installer-created packaged shortcut
continues to point directly to `Onyx.exe`.

## Transaction and rollback

- Frozen V7 transactional seams: 23.
- V8 shortcut seams: 1.
- Total installed V8 seams: 24.

If the V8 seam fails after V7 installation, it restores the exact installed V7
shortcut method and retains the post-V7 state. Normal V8 seam rollback does the
same. A separate test/termination helper can then unwind V7 to the original
host.

The recorded V8 rollback control invokes the complete canonical V7 activation
environment through the frozen V7 launcher. No rollback was executed live.

## Reproduced evidence

- Focused V8 pytest: `7 passed`.
- Frozen/default-off desktop regression: `4 passed`.
- Twenty-seven missing, partial, alias, and noncanonical V8 launch variants
  refused before host import.
- Bootstrap subprocess from an empty activation environment:
  `mode=active`, `hud=v5`, real Phase5 bridge, 26-entry main catalog, zero
  network calls.
- Simulated Windows COM receives the source Python executable and a separately
  quoted bootstrap argument.
- Two shortcut recreations produce the same link and exact five-field shortcut
  specification.
- No shortcut specification contains `scripts/launch_onyx.pyw`.
- A missing source `.venv\Scripts\pythonw.exe` target is rejected before link
  creation.
- Packaged/frozen Windows continues to use the packaged executable with no
  bootstrap argument.
- V8 seam failpoint restores the exact post-V7 state; full cleanup restores the
  original host.
- Frozen V7 external acceptance verifier passes.
- Ruff and Python compilation pass.

No duplicate-process prevention was added. That concern is outside this
single-shortcut regression and was not necessary to make shortcut recreation
deterministic.

## Honest execution boundary

The Windows link tests use simulated COM. The bootstrap is executed in a real
fresh Python process only through `--preflight-only`; it does not open the
physical UI, microphone, network, or Gemini.

V8 remains default-off. No live activation, process restart, shortcut write,
credential change, provider call, network call, or installed-package mutation
was performed.

## Candidate controls

- Desktop/source bootstrap: `scripts\bootstrap_onyx_live_v8.pyw`
- Canonical launcher: `scripts\launch_onyx_live_v8.pyw`
- Active control: `scripts\launch_onyx_live_v8_active.cmd`
- Post-V7 rollback control: `scripts\launch_onyx_live_v8_rollback.cmd`
