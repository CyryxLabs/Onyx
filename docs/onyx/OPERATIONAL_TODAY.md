# Onyx Operational Today checkpoint

Status: **historical 2026-07-19 checkpoint; superseded by
`CURRENT_RELEASE_STATUS.md`.** Retained as immutable operational history; it is
not evidence for the current release candidate.

Status: Windows source-checkout operational slice, captured on 2026-07-19.
This checkpoint does not claim completion of Phases 4-16 or a signed release.

## Included today

- Onyx launches from the owner's `Desktop\Onyx.lnk` without a console.
- `scripts/launch_onyx.pyw` records startup failures in
  `runtime/logs/onyx-startup.log` before importing the production runtime.
- The existing production path remains authoritative: Qt UI, microphone,
  Gemini Live, speaker queue, tools and HTTPS dashboard.
- Owner autonomy is enabled for routine work. Autonomous file mutations remain
  limited to the configured owner roots; system/repository paths, reparse-point
  escapes, deletion, shutdown/restart and executable code remain protected.
- The LAN dashboard listens on private-network ports 8000 and 8001. The owner
  opens `REMOTE` in the trusted desktop UI to generate a one-time PIN/QR token.

## Evidence captured

- Offline readiness: installation baseline passed, including runtime import,
  credential metadata, Chromium, HTTPS dashboard and writable runtime layout.
- Selected physical/service readiness: ambient microphone capture passed and
  Gemini Live completed a real text-to-audio turn.
- Production runtime startup log: Gemini connected, microphone stream opened,
  receive loop started, speaker loop started and dashboard bound to both ports.
- Production conversation: the main Gemini session returned the exact requested
  response `Onyx operacional.` and subsequently invoked routine memory, game,
  search and system-status tools.
- Owner-autonomy focused regression: 5 tests passed, covering routine execution,
  protected paths, destination escape denial, audit chaining/redaction and
  audit-failure denial.
- Five-second idle sample: approximately 0.09% host-normalized CPU and 341 MB
  working set for the production process on this machine. UI CPU/RAM telemetry
  is host-wide, not per-process.
- Launcher smoke: two `pythonw.exe` launcher/runtime processes were present and
  HTTPS ports 8000 and 8001 were listening after startup.

## Honest limits

- The fixed-phrase integrated readiness probe did not receive a completed Live
  turn during its capture windows. The production session later received user
  requests and invoked tools, so this remains a diagnostic-probe discrepancy,
  not proof that every physical voice turn will succeed.
- A physical phone must still accept the self-signed local certificate and pair
  through a fresh one-time PIN/QR. Loopback/LAN server and firewall state cannot
  prove the phone/browser path by themselves.
- This is not an installer, signed artifact, macOS/Linux certification or final
  cinematic shell acceptance.

## Deferred blocks

The default-off P4.4 R6 work and master-plan Phases 5-16 remain preserved for
subsequent reviewed development. They include governed grants, Capability Nexus,
model routing/MCP, Company Graph, executive connectors, intelligence, social,
Project Autopilot, paid growth, travel, knowledge refinery, final spatial HUD
and cross-platform release hardening.
