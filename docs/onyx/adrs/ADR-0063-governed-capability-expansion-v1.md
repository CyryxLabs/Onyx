# ADR-0063 — Governed Capability Expansion V1

Date: 2026-08-23  
Status: Accepted for default-off engineering implementation  
Story: `docs/stories/ONYX-MARK-LI-BROWNFIELD-GAPS-V1.story.md`

## Context

The owner requested the remaining capability gaps identified in the Mark-LI
comparison: enhanced Gemini Live audio, extensibility, clipboard assistance,
personalization, wellness counters, caption generation and social upload. The
reference repository is CC BY-NC; its source is not an implementation input.

Onyx already owns the permission broker, grants, audit, workspace identity,
Phase 10 brand/content records and outcome reconciliation. A second authority
plane would make external effects and plugins materially less safe.

## Decision

1. Every new capability is CLI-first, independently default-off and projects
   status from host-owned records.
2. Enhanced Live audio may request provider-supported affective dialog and
   proactive audio. Unsupported or failed negotiation falls back once to the
   existing approved audio configuration and never grants tool authority.
3. Plugins use versioned manifests and digest/provenance records. Dispatch is
   blocked unless an injected native-sandbox capability returns a fresh HMAC-
   authenticated attestation bound to the exact command, IPC payload,
   environment, working directory and timeout. Child-process separation alone
   never enables execution; every host capability remains brokered.
4. Clipboard assistance is explicit-snapshot only. V1 adds no startup read,
   background polling or ambient clipboard authority.
5. Personalization separates inferred records from owner-confirmed records and
   cannot change authority, risk, account selection or workspace scope.
6. Calorie and exercise data is private tracking. Model/vision estimates remain
   drafts until owner confirmation and carry no medical or outcome claim.
7. Caption generation is a local draft operation with provenance and stable
   request identity. It has no publication side effect.
8. Social mutation follows one boundary:

   `preview -> exact consent -> one dispatch -> provider receipt -> read-back -> verified | reconciliation-required`

   Payload, account, media or target drift invalidates consent. An ambiguous
   post-dispatch outcome is never blindly retried. Official provider adapters
   are separate from the existing read-only Phase 10 connector.
9. Credentials, raw clipboard text, media and tokens do not enter ordinary
   audit records, plugin environments or receipts.
10. Implementation is original Cyryx clean-room work. No Mark-LI code is copied,
    translated, vendored or mechanically derived.
11. A vision repetition estimate consumes only a normalized, confidence-scored
    vertical signal. The estimator opens no camera, receives no frame, retains
    no identity data and returns a draft requiring owner confirmation. Binding
    it to the existing camera owner requires a new authenticated successor; V1
    CLI evidence does not claim live-camera composition.
12. A local social video is represented by a short-lived process-local lease
    bound to its digest, size, MIME, principal and workspace. The durable social
    preview stores the opaque binding, never the raw local path. Mutation,
    symlink drift, scope drift, expiry and restart invalidate dispatch and
    require a new preview and consent.

## Consequences

- Provider-free contracts and fake-adapter tests can be accepted locally.
- Live social upload remains unavailable until an official adapter, owner
  credentials/scopes, test account and authenticated read-back are supplied.
- A child process alone does not qualify any plugin for execution. An
  authenticated native-sandbox adapter remains an external runtime prerequisite.
- Optional UI controls may be added only after their CLI/runtime authority is
  proven and must not create a separate control plane.
- Video lease resolution supplies a path only to the injected official adapter
  in-process. No adapter is included or activated by this decision.

## Verification boundary

Passing local tests proves default-off contracts, state transitions and failure
handling. It does not prove Gemini preview availability, native plugin sandbox,
provider certification, live social publication, installed-host packaging or a
public release.
