# Voice session authority V1 — sources and design basis

Hermetic, deterministic session-authority contract. No external service is
used; the basis is the owner's recorded decisions, the permission broker's
existing extension point, and the accepted-but-shadow grant/inbox slices.

## Basis

- Capability matrix, `Exact permission broker` row limitation: *"No persisted
  bounded grants or approval inbox."* That single line is the cause of the
  owner's day-to-day friction, since every consequential action prompts
  individually and nothing can be pre-authorized.
- Capability matrix, `Bounded session grants/autonomy envelopes` next action:
  *"Build and independently accept the exact low-risk enablement slice; never
  waive always-explicit gates."* This slice is that step.
- `core/permission_broker.py`: `set_governance_authorization_hook`, documented
  in-source as "the V16 exact low-risk/kill authority", consulted before the
  trusted-host prompt in both `authorize_model_tool_decision_only` and
  `authorize_model_tool`. Returning a concrete decision short-circuits the
  prompt; returning `None` leaves the legacy path untouched. The hook contract
  is `Callable[[str, Mapping], tuple[bool, str] | None]`.
- `core/session_grants_v11.py` (accepted, `VE-P51-GRANTS-R11-E6-001`): shadow
  evaluator only — `ShadowGrantDecision` fixes `authority_granted=False` and
  `callback_required=True` as `init=False` fields, so it cannot grant. Its
  `HostActionPolicy` supplies the vocabulary this slice reuses conceptually:
  `always_explicit`, `risk`, `capability`, `tool`, `operation`.
- `core/approval_inbox_v15.py` (accepted, `VE-P52-APPROVAL-INBOX-V15-E6-001`):
  read-only projection, `authority_granted=False` throughout.
- `core/permission_broker.py` `MODEL_TOOL_ACTIONS`: the exact tool/action
  vocabulary the envelope and always-explicit sets are drawn from, so no
  invented operation name can enter either set.

## Owner decisions encoded (2026-08-19)

- Voice alone opens the envelope; no confirmation step. Recorded with the
  accepted spoofing exposure, since Onyx has no speaker verification.
- Scope is read + write + local development over the authorized roots.

## Design decisions

- **Kill switch is the first rule**, and it also closes the envelope and
  blocks reopening.
- **Always-explicit is absolute**, including `file_controller.delete` inside
  an authorized root — deletion is the least reversible local action.
- **Whole-component root containment**, so `C:\Work2` can never pass as
  inside `C:\Work`; nine argument keys are inspected.
- **Bounded envelopes** — lifetime 1 minute to 8 hours, cap 1 to 10,000.
- **Three-word exact trigger** — the cheapest defence against incidental
  audio, at no cost to the owner.
- **`None` is the default answer**, so anything unrecognised keeps the
  existing approval behaviour unchanged.
