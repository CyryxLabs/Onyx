# Onyx — Operational Release Cut (2026-07-19)

Status: **historical release-cut plan; superseded by
`CURRENT_RELEASE_STATUS.md`.** The decisions below describe the 2026-07-19
slice and must not be used as current completion or release evidence.

## Decision

The delivery target for today is the existing production assistant path. Large
governance and enterprise extensions remain isolated and default-off until their
own acceptance gates pass. They are not release dependencies for this cut.

## In scope today

- Desktop launch through `C:\Users\ppetr\Desktop\Onyx.lnk`.
- Cyryx Onyx Qt/HUD interface and low-idle-cost 3D Orb fallback.
- Gemini Live conversational session with microphone and speaker streaming.
- Existing tool dispatch, durable local memory and mission worker.
- Owner Autonomy for routine work inside configured owner roots.
- Explicit protection for system paths, repository internals, executable code,
  destructive operations and other irreversible actions.
- Authenticated local/LAN dashboard on HTTPS ports 8000 and 8001.
- Startup diagnostics in `runtime/logs/onyx-startup.log`.

## Acceptance evidence for this cut

- Capability Nexus current source integrity is gated by
  `VE-CAPABILITY-NEXUS-CURRENT-V1-E6-001` and
  `docs/onyx/acceptance/VE-CAPABILITY-NEXUS-CURRENT-V1-E6-001.manifest.json`:
  exactly 32 implementation/test versions are bound, while the 32 predecessor
  artifact manifests remain immutable historical-only evidence.
- The current operational input set reconstructs 7/7 under
  `docs/onyx/VE-OP-TODAY-003.sha256`; prior manifests remain historical.
- The production runtime is connected and its microphone, receive and playback
  loops are active.
- `python -m core.readiness --json` reports `install_ready: true`; runtime import,
  credential vault, Chromium, dashboard and runtime directories pass.
- `https://127.0.0.1:8000` and `https://127.0.0.1:8001` respond with HTTP 200.
- Focused autonomy/dashboard regression selection: 8 passed.
- The accepted isolated P4.4/R10 candidate is not imported or activated by `main.py`.

## Test now

1. Open Onyx from the desktop shortcut.
2. Say: `Onyx, diga apenas: sistema operacional.`
3. Ask: `Qual e o status deste computador?`
4. Ask Onyx to remember one harmless preference and then ask for it again.
5. For the phone, click `REMOTE` on the desktop UI, open
   `https://192.168.1.236:8001`, accept the local certificate once, and pair with
   the fresh PIN/QR.

The phone gate is accepted only after the startup log records
`[Dashboard] Remote device authenticated.`

## Deferred development blocks

1. **Governed autonomy:** Phase 4 E1-E6, bounded grants, approval inbox and a
   separate controlled activation/rollback decision for the accepted R10 slice.
2. **Capability expansion:** MCP/connectors, model routing, calendar, email and
   company/workspace graph.
3. **Proactive operations:** reviewed briefing, daily planning, follow-ups and
   long-running operator workflows with cost controls.
4. **Experience:** final spatial/cinematic HUD refinements and physical GPU
   frame-time certification.
5. **Distribution:** signed Windows installer plus clean-machine macOS and Linux
   builds, notarization and release certification.

These blocks extend the product; none replaces or modifies today's stable voice,
tool, memory, autonomy or dashboard engine.
