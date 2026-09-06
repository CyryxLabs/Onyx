# Capability delta — Phase 8 Microsoft Graph OAuth V1

## Added behind one exact default-off flag

- Microsoft identity platform device authorization for a public native client.
- Exact read-only delegated scope admission.
- Signed-in account verification through Graph `GET /me`.
- Refresh-token-only native-vault persistence and rotation.
- Process-local access-token caching with explicit memory-wipe limitation.
- One-shot device-session consumption on successful token endpoint response.
- GET-only bearer transport composed with accepted Graph Read V1.
- Honest disconnected state on refresh failure without destructive token
  deletion.

## Not added

- Entra app registration, production client ID, tenant consent or test account.
- Live identity or Microsoft Graph E2E.
- Provider-side draft or any calendar/mail mutation.
- Automatic rate-limit retry.
- Startup, V13, voice, dashboard or UI wiring.
- Phase 8 aggregate exit or full PRD completion.

