# Capability delta — Phase 8 Microsoft Graph Live Read V1

## Added behind one exact default-off flag

- Resilient live GET transport for the accepted Graph read adapter.
- One forced token refresh and one retry after `401`.
- Terminal `403` permission/license classification.
- `429 Retry-After` handling without early retry.
- Bounded exponential retry when `Retry-After` is absent.
- Bounded retry for `500`, `502`, `503` and `504`.
- Payload-free last-operation telemetry with request ID.
- Direct composition with the accepted calendar/mail executive brief.

## Not added

- Authorized Entra registration, tenant consent or test account.
- Claimed live-provider execution or E6 acceptance.
- Calendar conflict/create, email provider draft/send, tasks or OneDrive.
- Any POST/PATCH/DELETE Microsoft Graph route.
- Startup, V13, voice, Orb, dashboard or UI wiring.
- Phase 8 aggregate exit or full PRD completion.
