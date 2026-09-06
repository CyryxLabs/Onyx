# Onyx Live Activation V4 — Live Rejection Record

Status: **REJECTED FOR LIVE USE; ACCEPTED BYTES PRESERVED**

The independently accepted V4 candidate was activated after its original gate
and failed in the real Gemini Live path.  The activation was rolled back to the
legacy launcher.  No accepted V4 artifact was edited after the incident.

## Observed live failure

- Gemini Live returned WebSocket/API error `1007`: audio content type
  `CONTENT_TYPE_AUDIO` was not supported for the active model configuration.
- The production sender used `audio/pcm`, while the already accepted readiness
  probe used the supported contract `audio/pcm;rate=16000`.
- The host classified every `1007` as an invalid API key, displayed the setup
  overlay, and therefore created a misleading reconfiguration path.
- A provider TaskGroup exception ended the active voice session.  One reconnect
  was observed, but the log had no clean V4 stop record before rollback.
- The setup overlay and the V5 HUD setup surface were simultaneously visible.

## Disposition

- V4 remains immutable evidence and is not a live candidate.
- Legacy launch was restored.
- Activation V5 is isolated around V4 and must pass an independent gate before
  any live activation.  Its scope is provider-failure containment, exact audio
  negotiation, action replay suppression, circuit recovery, and one setup
  projection.

