# ADR-0036 — Phase 8 Microsoft Graph Read V1

- Status: candidate
- Date: 2026-07-23
- Depends on: accepted Phase 7 Exit Candidate V1

## Decision

Prove the first executive-office provider with an exactly default-off Microsoft
Graph v1.0 adapter. Bind it to one accepted workspace/principal credential
alias and an injected GET-only transport. The adapter may read a bounded
calendar view, build a normalized daily brief, search mail metadata, read one
message when body scope is present and create local immutable event/email
drafts.

Every provider operation re-attests the alias, workspace, principal, scopes,
rotation deadline and revocation state. Paging remains on the exact initial
Graph origin and route. Message bodies are always untrusted content and are
never persisted or written to general memory/audit by this module.

## Authority boundary

The transport protocol contains only `get`. Local drafts carry
`mutation_authority=false`. V1 cannot create an event, create a provider draft,
send mail, update, cancel or delete anything. Later mutation successors must
require their own exact grant/approval contracts and must not weaken this
candidate.

## Consequences

- Calendar read/brief/local-draft and mail search/read/local-draft contracts
  are implemented for one provider.
- `Calendars.ReadBasic` and `Mail.ReadBasic` are accepted for metadata.
  Message body reads require `Mail.Read` or `Mail.ReadWrite`.
- Provider pagination is capped at five pages and 250 normalized records.
- OAuth onboarding, live HTTP transport and all external mutations remain
  outside this candidate and Phase 8 aggregate exit remains pending.

## Rollback

Leave `ONYX_PHASE8_MICROSOFT_GRAPH_READ_V1` unset. The factory returns before
Phase 7 entry verification or any alias/transport access.
