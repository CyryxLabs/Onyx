# Onyx V11 live promotion — 2026-07-23

> **SUPERSEDED FOR CURRENT-STATE CLAIMS.** This is immutable V11 observation
> evidence, not proof of the current installed runtime. See
> [`CURRENT_RELEASE_STATUS.md`](../CURRENT_RELEASE_STATUS.md).

Activation V11 C001 was promoted after its candidate and E6 gates passed.

## Live identity

- shortcut bootstrap: `scripts/bootstrap_onyx_live_v11.pyw`;
- process chain: parent `pythonw.exe` plus live child;
- live child PID at validation: `51980`;
- title: `Onyx — Cyryx Labs`;
- responsive: yes;
- live screenshot: `runtime/logs/onyx-v11-live-screen.png`;
- visual review: accepted V8 Orb, no external orbit arcs.

## Operational evidence

- voice provider connection initiated successfully;
- microphone stream open;
- receive and playback workers started;
- Gemini returned a response and requested `save_memory`;
- `save_memory` executed and persisted approved `identity/language` memory;
- a subsequent `file_processor` tool request was received;
- ports 8000 and 8001 listened on `0.0.0.0` under the live V11 PID;
- localhost and `192.168.1.236` returned HTTP 200 on both HTTPS ports;
- Ethernet profile was Private;
- enabled inbound Private-profile firewall rule `Onyx Dashboard LAN` allowed
  TCP ports 8000-8001.

## Resource sample

- visible normalized CPU: 0.3972%;
- minimized normalized CPU: 0.1534%;
- working set: 365.6 MB;
- private allocation: 1068.2 MB;
- threads: 99;
- process responsive: yes.

These are one settled Windows sample, not cross-device guarantees. The private
allocation remains materially higher than the resident working set and is a
future memory-optimization target; CPU is low.

## Remote address

The current LAN address is `https://192.168.1.236:8001` (port 8000 also
responds). A phone on the same non-isolated `192.168.1.0/24` LAN must accept
the local certificate once. Local HTTP 200 and the inbound firewall rule do
not prove that a Wi-Fi access point has client isolation disabled.
