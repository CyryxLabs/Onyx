# Onyx 1.1.9 V31 Windows acceptance

> **SUPERSEDED FOR CURRENT-STATE CLAIMS:** this remains exact V31 historical
> evidence. R10B is the current installed candidate; use
> `../CURRENT_RELEASE_STATUS.md` and
> `../DOCUMENT_SUPERSESSION_REGISTRY_R10B_2026-08-11.md` for current truth.

Status: **exact-installed operational candidate; long-session and formal
release gates remain open**.

## Candidate identity

- Phase 5: V31 SHA
  `1cf1cd04e9d9cdb07b64cd98aaff051e9369596cf248099c4c293d5fce352ef4`.
- Release Workflow: V19 SHA
  `159c7e167b7340030930a9267b9a6754fbad1a5ec9a8e10534c24a90fc5b4ddc`.
- Build-input root:
  `1cc9402bb7d08480ab2e042ce45e0ead9c12784cf15a819fe8446fac2d7b58c9`.
- Bundle root:
  `598f782412da720cedf11365e481c6c03f851219f5ef8cb81d0e3291cf99512e`.
- Setup SHA-256:
  `0cdce50e660724729e44b145a57a695945777932d78c1ccc5ee54e6c740f178b`.
- Portable SHA-256:
  `d7d0880c7dab5155eb4ac2728c81570fef910c11e0ab177dc96dfb9e61751012`.
- SPDX SBOM SHA-256:
  `d28acfdee90ac8ef1601432beb00bd0e85e4bc9da0b468c20dce5ca16db2ee98`.

## Passing gates

1. Installer exit 0.
2. Exact 9,769-file comparison: zero missing, mismatched or unexpected files.
3. Eleven packaged executable smokes passed with empty stderr.
4. Normal interactive V23 startup remained responsive and recorded microphone
   start/open, playback start, Gemini Native Audio connection and receive start.
5. Windows inspection showed `Sir`, `PRESENT`, `VOICE READY`, Onyx/Cyryx Labs
   branding and the central arc-free cinematic Orb.
6. A ten-second process sample measured `0.7533%` whole-host-normalized CPU,
   425,549,824 bytes working set and 1,178,484,736 bytes private memory.
7. Installed mission recovery used the installed module SHA
   `7af0c456d14f3e8a3d6dcb49eca017521b386e5d6f519f9f8057abcab5111327`.
   A child exited 73 after `step.started`; restart recovery reached `waiting`,
   made zero blind replay, preserved the idempotency key and succeeded only
   after one explicit retry. Pause, cancel and the ten-event audit passed.

## Active gate

The exact V31 eight-hour monitor writes to
`C:/MAAX_Assistant/Onyx-V31-Windows-Candidate-20260804/ONYX_1_1_9_V31_WINDOWS_LONG_SESSION_RECEIPT.json`.
Only `status=passed`, `full_duration=true` and thresholds satisfied after at
least 28,800 seconds can close this gate.

## Evidence location

The frozen artifacts, inventory, SBOM, receipts, logs and evidence index are in
`C:/MAAX_Assistant/Onyx-V31-Windows-Candidate-20260804`.

## Open boundaries

- Owner acoustic judgment and one spoken name mutation across restart.
- State-specific Orb motion/frame/thermal observation and completed soak.
- Signed disposable-host lifecycle, Graph, physical Linux/macOS, legal approval
  and independent review.

The V31 artifact is an unsigned `untrusted-candidate`, not a formal release.
