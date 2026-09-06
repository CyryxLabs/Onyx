# Onyx HUD / Orb V5 Live External E6 Acceptance

- Evidence ID: `VE-HUD-ORB-V5-LIVE-E6-001`
- Decision date: 2026-07-22
- Decision: **ACCEPTED - HUD / Orb V5 Live Candidate 003 only, frozen default-off handoff**
- Candidate: `ONYX-HUD-ORB-V5-LIVE-INTEGRATION-003`

## Frozen candidate anchor

This independent record freezes Candidate 003 without changing any candidate
byte, restarting Onyx, or enabling its activation flag.

| Anchor | SHA-256 |
|---|---|
| `docs/onyx/checkpoints/hud-orb-v5-live/manifest.json` | `1b5415c70322cbdbb315046b7ef2a772c16d53a2db0ab326739265fd0d52152a` |
| `docs/onyx/checkpoints/hud-orb-v5-live/ONYX_HUD_ORB_V5_LIVE_CHECKPOINT.md` | `fd482f6cbc4d4dba849d980ccc3aa6d83f6a9e7b67b691e5df489fe28c729f9f` |
| `ui.py` | `e5768626b7eb9d162a54cd67b08b5cb7d9685fb5c0e1b8c951843a1146fc252b` |
| `qml/OnyxLiveShellV5.qml` | `9ff4d3d5d3771d1bbf2c2f8fe68793fd05e8cc80fd0c0644d700596d7cd39e47` |
| `qml/components/OnyxOrbCinematicV5.qml` | `adff9ee062fff1c735bd28d4a77591581b6e4ce131067b1724699da5055e2622` |
| `qml/assets/onyx-orb-cinematic-v3.png` | `44668e57df10b4b47516cf7b35238ced7803523c76ea264a2045bdb35b174de1` |
| `tests/test_onyx_hud_v5_live_integration.py` | `93c3854d866d739adb261cfb241a40d20d34f25a22747f89b049a5c21caf5cfc` |

The exact candidate-manifest digest
`1b5415c70322cbdbb315046b7ef2a772c16d53a2db0ab326739265fd0d52152a`
is the frozen root for this decision. Its 13 candidate records and four
accepted V3 anchors are independently rehashed by the acceptance verifier.
Any drift invalidates this decision and requires a new candidate and new gates.

## Independent gate decision

The independent acceptance gate is **PASS** with `P0=0, P1=0, P2=0`.
It independently rehashed the candidate closure, checkpoint, rejected
predecessor snapshot, inherited physical screenshot and live boundary anchors.
It also reproduced **15 passed, 0 failed** in the V5 suite and **66 passed, 0
failed** in the representative HUD/governor/Orb/packaging/dashboard matrix,
including the current `tests/test_orb_3d.py`.

The exact `tests/test_orb_3d.py` used by that matrix is bound at SHA-256
`01be59d1438621b6d16c1723feebe3b12cc0dcae006bffff076ba5bffc86411d`.
The verifier rehashes all 11 matrix files, not only their path names or counts.

The only release advisory is P3: physical renderer/runtime evidence is limited
to Windows with `GraphicsApi.Direct3D11Rhi` at 1440x900. Native macOS and Linux
renderer/package behavior requires later testing on real hosts. This does not
weaken the frozen Windows evidence or the default-off software contract.

## Exact default-off and activation boundary

The only Candidate 003 opt-in is the exact comparison
`os.environ.get("ONYX_HUD_V5_LIVE", "0").strip() == "1"` in the frozen
`ui.py`. Therefore an absent flag defaults to `False`; ambiguous/truthy values
do not activate it. Rejected `ONYX_HUD_V3_LIVE` and `ONYX_HUD_V4_LIVE` flags
are absent from the current UI.

The host boundary remains exact and contains no `ONYX_HUD_V5_LIVE`,
`HUD_V5_LIVE`, V5 shell or V5 Orb activation reference:

| Host boundary | SHA-256 |
|---|---|
| `main.py` | `6b82fed0d7c932a08d2d1f8a31d7650a1b235d55085ee608fdbb7651e5f49712` |
| `core/permission_broker.py` | `e37fb092410ba0843036dbdc779342c4d24a811bbfcf0de8812f2f6144e7d250` |
| `dashboard/server.py` | `4d3142dc9c6a78cfe76f804de2b154334da2d7790484783a993babc92300bae1` |

No main, broker or server activation was added. No Onyx process was restarted,
no live flag was enabled, and this acceptance is not an activation instruction.

## Rejected Candidate 002 and inherited screenshot

Candidate 002 remains rejected and has no live activation flag. Its exact
13-file, 2,095,770-byte snapshot is preserved at
`docs/onyx/checkpoints/hud-orb-v4-live/candidate-002-snapshot/`.

| Rejected/inherited anchor | SHA-256 |
|---|---|
| Frozen Candidate 002 manifest | `8daf7a43fd08ee6d7548992f4a8ef2da48c4271142dabae4e8fb0ee76c50d495` |
| Frozen Candidate 002 checkpoint | `42148552f863791979812f19b1019921ce9b785153f511f80803e40d127126d5` |
| Candidate 002 rejection marker | `efff92bcecfc04770db135a19edc8c6846f5d8e0a3be34ac201e6e0d26e8fc92` |
| Inherited physical Windows/D3D11 screenshot | `03b99d56a542d48680c5baa42ffd818e20c6e87043dc82333d098be662ee57a1` |

Candidate 003's two visual QML files differ from Candidate 002 only by the
V4-to-V5 identifier transition, and the Orb asset is byte-identical. The
inherited screenshot is therefore represented as inherited evidence, not as a
new capture. Candidate 002 is not retroactively accepted.

## Reproduction commands

Exact V5 command - 15 passed, 0 failed:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_onyx_hud_v5_live_integration.py --basetemp .pytest-hud-v5-acceptance-15
```

Exact representative command - 66 passed, 0 failed:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_onyx_hud_v5_live_integration.py tests\test_onyx_hud_v4_live_integration.py tests\test_onyx_hud_v3_live_integration.py tests\test_onyx_hud_v3.py tests\test_orb_3d.py tests\test_ui_orb_performance.py tests\test_render_governor.py tests\test_render_governor_v3.py tests\test_packaging_paths.py browser_tests\test_dashboard_audio_worklet.py browser_tests\test_dashboard_device_token.py --basetemp .pytest-hud-v5-acceptance-66
```

Independent acceptance verifier:

```powershell
.\.venv\Scripts\python.exe -I -S -B scripts\verify_hud_orb_v5_live_acceptance.py
```

The verifier must emit `HUD_ORB_V5_LIVE_ACCEPTANCE_OK`.

## Exact acceptance boundary

Accepted:

- the exact frozen Candidate 003 manifest, candidate closure and V3 anchors;
- the default-off UI integration, one-Qt-Quick-renderer lifecycle, minimized
  suspension and 16-to-12 FPS governor contract;
- the exact rejected Candidate 002 preservation and inherited Windows/D3D11
  visual evidence;
- the static no-activation boundary in `main.py`, `core/permission_broker.py`
  and `dashboard/server.py`.

Not activated or accepted by this decision:

- setting `ONYX_HUD_V5_LIVE=1`, restarting Onyx or changing a service;
- a claim that the inherited screenshot is a fresh Candidate 003 capture;
- native macOS/Linux physical renderer or installer validation;
- Phase 5 activation/exit, later PRD phases, packaging release, or completion
  of Onyx as a whole.
