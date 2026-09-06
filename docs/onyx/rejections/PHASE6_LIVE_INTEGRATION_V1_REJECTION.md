# Phase 6 Live Integration V1 rejection

Status: **REJECTED — preserved, default-off, never live**

Date: 2026-07-23

Frozen V1 manifest SHA-256:
`56b8d2ae00078bd755dab583da922d0530b8d2e5482080704f62bc58f05ed6a7`.
Frozen V1 artifact root:
`4f974bdef7fbf58a6fb3780d5d3158884240ce9e4984401c67025b5eb26089bd`.

The independent gate found two P1 defects:

1. **Incomplete host identity binding.** V1 bound the Agentic Core, text and
   catalog paths by workspace but did not immutably bind and compare the full
   `workspace_id + account_id + profile_id + principal_id` tuple. Those fields
   were not present together in every V1 request digest and receipt. A facade
   could therefore be composed over a Phase 5 account, profile or principal
   different from the intended host authority.
2. **Operational construction admitted arbitrary dependencies.** V1's public
   constructors accepted an arbitrary text invoker and executor, and its facade
   factory accepted a prebuilt text adapter. The test seam was therefore also
   reachable from an operational construction path; V1 did not prove that live
   construction used only `_current_llm_text_call` and the exact
   `TerminableProcessExecutorV4`.

Disposition:

- V1 remains byte-exact, default-off, unwired and never activated.
- No V1 manifest, code, test, ADR, checkpoint or verifier is edited.
- V2 is a separate additive candidate. It must attest the complete host
  identity before constructing files or processes, bind that identity into all
  V2 request/receipt digests, internally construct the exact operational text
  invoker/executor, reject post-construction drift and expose no invoker,
  executor or prebuilt-adapter parameter on its operational factory.
- V2 does not retroactively accept V1 and does not authorize live wiring or
  Phase 6 exit.
