# Phase 8 Microsoft Graph OAuth V1 — Official Sources

Verified against Microsoft Learn on 2026-07-23.

## Device authorization

- [OAuth 2.0 device authorization grant](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-device-code)
  defines the `/devicecode` and `/token` endpoints, exact device-code grant
  value, polling interval, `authorization_pending`, `authorization_declined`
  and `expired_token` behavior, and the successful bearer/refresh response.
- Microsoft recommends its supported authentication libraries where possible.
  This V1 deliberately implements the documented protocol through the standard
  library because the accepted dependency manifest is frozen. An MSAL
  migration requires a separate dependency, packaging and compatibility gate.

## Public native client and registration

- [Public and confidential client applications](https://learn.microsoft.com/en-us/entra/identity-platform/msal-client-applications)
  classifies desktop/native software as a public client and explains that
  public-client flow should be enabled only when the application needs a
  supported public-client protocol such as device code.
- A real client ID must come from an authorized Microsoft Entra application
  registration. No client secret belongs in a public desktop client or this
  repository.

## Scopes and refresh lifecycle

- [Scopes and permissions](https://learn.microsoft.com/en-us/entra/identity-platform/scopes-oidc)
  states that v2.0 requests must explicitly include `offline_access` to receive
  refresh tokens.
- [Refresh tokens](https://learn.microsoft.com/en-us/entra/identity-platform/refresh-tokens)
  explains that refresh tokens can rotate, can be revoked, must be stored
  safely, and that the old token is not automatically revoked when a new token
  is issued.
- OAuth V1 therefore persists only the current refresh token in the native
  vault, accepts rotation after validation, treats revocation/refresh failure
  as disconnected state, and never serializes bearer or refresh tokens into
  status/evidence.

## Account and least privilege

- [Get user](https://learn.microsoft.com/en-us/graph/api/user-get?view=graph-rest-1.0)
  defines `GET /me` and identifies delegated `User.Read` as the least-privileged
  permission for the signed-in user's profile.
- [Microsoft Graph permissions overview](https://learn.microsoft.com/en-us/graph/permissions-overview)
  requires least privilege and distinguishes delegated access from app-only
  access.
- [Microsoft Graph permissions reference](https://learn.microsoft.com/en-us/graph/permissions-reference)
  distinguishes calendar/mail read scopes from write scopes. OAuth V1 rejects
  `Mail.Send` and `Calendars.ReadWrite` rather than treating a broad token as
  implicit mutation authority.

## Rate limits and live successor

- [Microsoft Graph throttling guidance](https://learn.microsoft.com/en-us/graph/throttling)
  requires honoring `429` and `Retry-After` and discourages immediate retry.
  OAuth V1 performs no automatic provider retry. Rate-limit behavior belongs to
  the separately gated live-read E2E successor so it can be verified with an
  authorized test account.

## Local limitations

- No real Entra application registration, client ID, tenant consent or account
  login is included in this candidate.
- The native-vault contract is exercised with injected doubles; host-specific
  Keychain/Secret Service/Windows Credential Manager behavior remains part of
  cross-platform live validation.
- Access tokens are process-local. Because Python strings are immutable, the
  implementation can drop references but cannot guarantee an in-place memory
  wipe.

