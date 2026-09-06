# Onyx Functional Parity V1

Date: 2026-09-02  
Reference repository: `https://github.com/FatihMakes/Mark-LI.git`  
Reference HEAD: `234dd792737f3acd38ca836aadae94c24ef0ad56`  
Functional parent: `c131a1b4f72e477bd4c6735142f3aaee36acc792`.

The current HEAD differs from the prior audited snapshot only by deleting the
reference `upload_video` and `pushup_counter` action modules. Onyx deliberately
retains its governed social-video and camera repetition equivalents, so the
current comparison is a functional superset and does not remove owner features.

## Result model

Onyx reports parity as six independent levels:

1. **Source contract** — an original Cyryx implementation and test evidence exist.
2. **Host-integrated** — an Onyx voice, local-host, governed CLI, or dashboard surface can reach it.
3. **Tested** — deterministic local tests pass for the declared boundary.
4. **Packaged** — the exact release candidate contains the implementation and passes package smoke.
5. **Installed** — the exact candidate is installed and passes installed-host smoke.
6. **Live verified** — required device/provider/OAuth/account behavior is observed end to end.

`core/capability_parity_v1.py` is the closed source-contract registry. Run:

```powershell
python scripts/onyx_parity_cli.py
```

The V1 registry contains 42 capability rows: all current non-visual core-feature
concepts plus the visible repetition/video actions and the owner-requested
calorie tracker. A successful report proves 100% **source-contract coverage**;
it deliberately leaves package, installed, and live-provider booleans false
until exact-artifact evidence exists.

## Clean-room and ownership

- Reference source was inspected for behavioral comparison against the exact
  snapshot. No reference module is vendored or imported by Onyx; the Cyryx
  implementations and tests remain native to this repository.
- The root `LICENSE` remains the Cyryx Labs LLC Software License Agreement.
- Product identity is immutable: Onyx by Cyryx Labs. An optional owner-selected
  call alias is conversational metadata only and cannot alter legal/product/UI
  identity.
- Product code, package IDs, executable names, prompts, UI, and evidence remain
  Onyx/Cyryx-owned. No foreign branding is introduced.
- By explicit owner decision, reference orb, reference layout, live theming and
  reference boot visuals are excluded. The accepted Onyx humanoid is immutable.

## Deliberately open operational gates

- plugin execution: certified native sandbox adapter;
- social upload: official adapter, OAuth/account binding, designated test target,
  exact consent, provider receipt, readback, and reconciliation;
- voice/affective/proactive audio: live supported Gemini session and physical audio;
- camera repetition: physical owner calibration;
- web/weather/flight/messaging/game/OS actions: their named live provider, device,
  client, or account;
- package/install: the exact candidate, manifest, package smoke, installer smoke,
  and rollback evidence are complete for the locally installed build; formal
  public distribution still requires Authenticode.

These gates do not reduce source-contract coverage, but they prevent a false
claim that the currently installed product or external accounts already have
100% operational parity.
