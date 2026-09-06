# Microsoft account connect — consumer UX spec (roadmap note, V1)

Status: design note for a future Phase 8 UI slice. Nothing here is wired; the
implementation must follow the normal versioned default-off checkpoint
protocol. Recorded 2026-07-24 after the first live read E2E run.

## Principle: zero technical fields

Commercial users never see or type: tenant ID, client ID, scopes, ports,
tokens or any environment variable. With a multi-tenant public-client
registration those concepts disappear from the experience entirely:

| Technical concept | Where it goes |
|---|---|
| Client ID | Compiled into the product (public identifier, no secret) |
| Tenant | Fixed literal `common` — Microsoft resolves the user's tenant from the e-mail at sign-in (the frozen settings validator already accepts `common`) |
| Account e-mail | Not asked upfront: discovered from live `GET /me` after sign-in and shown back to the user ("Conectado como …") |
| Refresh token | OS-native vault, per account, invisible |
| Scopes | Fixed read-only set at connect time; write scopes requested later per feature (incremental consent mapped to the exact-grant broker) |

## The flow (three steps, one decision)

1. **Settings → "E-mail e calendário" → button "Conectar conta Microsoft".**
   Copy states plainly: read-only, everything stays on this computer, nothing
   is sent to Cyryx Labs, disconnect anytime.
2. **System browser opens on the official Microsoft sign-in.** Primary path:
   authorization-code + PKCE via loopback redirect (no code to type). Fallback
   path (headless/remote shells): the proven device-code flow with the code
   pre-copied to the clipboard and the URL auto-opened. The password is only
   ever typed on microsoft.com — explicitly stated in the modal as an
   anti-phishing guarantee.
3. **Onyx detects completion**, verifies the signed-in account via `GET /me`,
   stores the refresh token in the native vault, creates the workspace
   credential alias automatically, and shows the connected card: account,
   what is enabled (read calendar, read mail) and what is locked (send,
   create — off until their future slices ship and the user opts in).

Connected-state card actions: "Adicionar outra conta" (multi-account via the
existing workspace aliases — personal vs. work) and "Desconectar" (deletes the
vault token via the accepted `disconnect()` contract).

## Error paths, in human language

| Condition | UX |
|---|---|
| Corporate tenant blocks user consent (AADSTS65001/90094) | "Sua empresa exige aprovação do TI." + button "Copiar link para o TI" (admin-consent URL) — never a raw AADSTS string |
| Account has no mailbox/license (`MailboxNotEnabledForRESTAPI`) | "Esta conta não tem caixa de e-mail. Use sua conta de trabalho ou Outlook.com." |
| Refresh revoked/expired (`invalid_grant`) | Card flips to "Reconectar" — one click, never destructive |
| Provider throttle (429) | Silent honor of Retry-After (already accepted behavior); no user-visible error unless persistent |
| Sign-in window expired | "O tempo esgotou. Tentar de novo." regenerates the code automatically |

## Commercial prerequisites (outside code)

1. Entra registration flipped to multi-tenant + personal accounts.
2. Microsoft Publisher Verification (Partner Center, verified cyryxlabs.com,
   public privacy policy and terms URLs) — without it, third-party tenants
   block consent.
3. Source ownership and commercial license are assigned to Cyryx Labs LLC in
   `OPEN_SOURCE_AND_API_LICENSE_REVIEW.md` (exact-artifact PySide6/Qt LGPL
   compliance remains gated on PRD Phase 16).

## Implementation mapping (when the slice is scheduled)

- Composes the frozen OAuth V1 session + Read V1 adapter + Device Bootstrap V2
  host fix; the PKCE/loopback variant is a new versioned successor of the
  bootstrap, not an edit to frozen files.
- The connect UI is a later Phase 8 slice, after the PRD-ordered calendar
  mutation and mail draft/send successors; it must ship default-off behind its
  own flag with the full checkpoint/evidence chain.
