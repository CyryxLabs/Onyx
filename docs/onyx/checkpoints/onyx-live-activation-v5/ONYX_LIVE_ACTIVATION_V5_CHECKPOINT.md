# Onyx Live Activation V5 — Candidate Checkpoint

Status: **CANDIDATE READY FOR INDEPENDENT GATE — NOT LIVE**

Activation V5 preserves the accepted host and V4 bytes and installs seven new
wrapper seams after the eleven accepted V4 seams.  Rollback restores all 18
installation writes in reverse order and then restores the exact V4/host
baseline.

## Corrected live contracts

1. Every PCM input message, from the PC or phone queue, is sent as the existing
   readiness contract `audio/pcm;rate=16000`.
2. Gemini `1007` audio-contract failures are not treated as credential errors.
   Credential setup is requested only for explicit invalid-key markers.
3. Provider `1007`, `1011`, network, and unknown session failures are contained
   by a bounded-backoff circuit breaker.  The local HUD, dashboard, mission
   worker, and process lifecycle remain outside the provider session.
4. Automatic half-open recovery and explicit `recover voice` / `recuperar voz`
   recovery are supported.  Stable voice closes the circuit and emits truthful
   UI/dashboard state.
5. Text/dashboard commands received without a provider session are refused and
   never buffered for replay.  Provider function-call IDs are retained for the
   process lifetime so a reconnect cannot execute the same action twice.
6. While setup is visible, the V5 renderer is suspended and the existing
   accessible `SetupOverlay` is the sole setup projection.  Repeated setup
   requests raise the same overlay.  Successful setup resumes the V5 renderer.

## Candidate evidence

- V5 focused pytest: `6 passed`.
- V4 acceptance plus V5 cumulative pytest: `29 passed`.
- Host gate: 18/18 atomic installation failpoints; exact MIME; separated
  1007-audio, 1011, and credential faults; duplicate tool call suppressed;
  exact rollback.
- Local fake-provider E2E: real V5 runtime supervisor reproduced `1007`, opened
  the circuit, automatically recovered on attempt 2, and remained connected for
  601 accelerated seconds.  HUD/process remained alive, dashboard/listeners
  started once, setup prompts were zero, and both attempts used the exact MIME.
- Real offscreen Qt gate: one visible setup surface, repeated setup idempotent,
  setup controls usable, V5 renderer suspended and resumed.
- Cumulative verifier: host + fake-provider + Qt; ten frozen host/V4 files
  matched; no network/provider call; no live activation.

## Preserved frozen boundaries

- `main.py`: `6b82fed0d7c932a08d2d1f8a31d7650a1b235d55085ee608fdbb7651e5f49712`
- `ui.py`: `e5768626b7eb9d162a54cd67b08b5cb7d9685fb5c0e1b8c951843a1146fc252b`
- V4 core: `2521b5dcf53172e73e23219e9266037f7312a233ef135281a1a2ac3660aec05b`
- V4 launcher: `a7bfc190cb95d49e871fcd312f32badbd1a5a6d18393ca725d214f1f66769af8`
- V4 cumulative verifier: `20426a7fd2e592dfa54b2a352928a941e01bd7798314bb3d21363a9c0e6bd597`
- V4 host gate: `e1e53cee11d1fbaf460d8690f9131da56c9773e75ffbd286345395c969fe2105`
- V4 Qt gate: `19015ebf96a32e449709831d86d90465e612ba63f770bea917f01dd21ab3b95b`
- V4 test: `4c776af560a7f3bfd470bef91d205fddbe509c6c767cbaad2b754f3023068783`
- V4 checkpoint: `3ea17bf227025f7dbe2ce4f91e15801151c6262efc01173657e7c3ce481d638f`
- V4 manifest: `ebe3b24e641d1148e3ddb3767705b593a0d9df0898ba2654b53cd7820e0d6c09`

## Gate boundary

The candidate intentionally made no real Gemini call and did not start, stop,
or replace the currently running Onyx process.  A separate independent review
must verify this manifest and rerun the gates before a controlled live
activation.  A successful fake-provider gate proves failure containment; it is
not evidence that the external Gemini service is currently available.

## Candidate launch controls

- Active candidate: `scripts\launch_onyx_live_v5_active.cmd`
- Exact rollback: `scripts\launch_onyx_live_v5_rollback.cmd`
- Preflight only: set the complete V5 activation environment and run
  `.venv\Scripts\python.exe -B scripts\launch_onyx_live_v5.pyw --preflight-only`

