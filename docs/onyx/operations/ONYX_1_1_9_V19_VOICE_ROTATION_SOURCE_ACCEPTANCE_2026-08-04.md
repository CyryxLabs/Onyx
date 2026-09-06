# Onyx 1.1.9 V19 voice-rotation source acceptance

> **SUPERSEDED FOR CURRENT-STATE CLAIMS.** This exact V18/V19 defect and source
> correction record remains historical evidence only. Use
> [`CURRENT_RELEASE_STATUS.md`](../CURRENT_RELEASE_STATUS.md).

Status: **SOURCE ACCEPTED — REBUILD REQUIRED**  
Observed: 2026-08-04 UTC

## Failure reproduced on installed V18

Installed `Onyx.exe` PID 43560 started Gemini Native Audio, microphone,
receiving and playback normally. At the first provider `GoAway`, the process
terminated with Windows Application Error `0xc0000409` in `ucrtbase.dll`.
The formal monitor recorded one responsive sample and failed after 60.305
seconds with reason `process_exited_before_duration` and one Application Error.

Receipt:
`%LOCALAPPDATA%/Cyryx Labs/Onyx/runtime/verification/onyx-1.1.9-v18-soak-attempt1-receipt.json`.

## V19 correction and real-provider result

V19 separates native audio ownership from Gemini transport ownership.
Microphone and playback start once around the provider supervisor; only the
network send/receive tasks and session transport rotate. Input is discarded
while no provider session is active, and stale session queues are drained at
the transport boundary.

A source execution using the operational owner profile and existing secure
credential produced a real `GoAway`, reconnected and started a second receive
session. The process remained responsive. Counts after the rotation were:

- provider rotation observed: yes;
- receive starts: 2;
- microphone starts: 1;
- playback starts: 1;
- system-voice fallback: none;
- process state: responsive.

The focused voice selection passed 26 tests, the activation-plus-voice
selection passed 162 tests, the transition selection passed 32 tests and the
integrated 35-suite selection passed 252 tests. These results do not substitute
for a clean V19 build, exact install, installed rotation receipt or the formal
eight-hour gate.
