# Phase 5 Integration V2 transition checkpoint

Date: 2026-07-22

Status: candidate implemented and verified as default-off. No live activation or
restart was performed.

## Historical governance

The external Runtime V10 E6 record remains immutable evidence that V10 was
accepted while isolated, default-off and unwired. Its source, tests, candidate
manifest, checkpoint, E6 record, record manifest, verifier, and verifier tests
remain byte-for-byte unchanged. The frozen verifier is not weakened or rewritten
to describe the later integration state.

Integration V1 is retained byte-for-byte as rejected historical evidence and is
not reachable from the host. The host imports only Integration V2.

## V2 correction

V2 stores every material local catalog read argument in an immutable normalized
record and binds its canonical SHA-256 digest to the prepared decision. Immediately
before adapter dispatch, V2 re-normalizes and compares the exact arguments and
digest. Any mutation, invalid field, replay, or concurrent duplicate burns the
decision, purges all state for that invocation, emits a bounded audit event, and
never reaches the catalog adapter. Invocation references are also retained in a
bounded anti-replay window; duplicates and post-consume reuse are rejected and
audited without replacing the original prepared decision.

The only executable extension remains provider-free, read-only
`local.catalog/catalog_read`. It has no mutation, credential, egress, provider,
remote approval, remote grant, or remote dispatch authority.

## Reserved surface

This phase did not modify `ui.py`, QML, the Orb/HUD, or dashboard static assets.
Those files are under a separately authorized concurrent HUD V3 transition and
their current bytes are explicitly outside this checkpoint's authority. The
pre-parallel `ui.py` hash is retained only as a historical observation; it is not
claimed as current. V2 is proven to have no import, reference, or dependency on
those surfaces. The permission broker and dashboard server remain at their exact
V1 generic-hook hashes. Only the minimal host import, factory, and V2 default-off
environment names changed in `main.py`.

## Verification boundary

The transition verifier first proves all frozen V10/E6 bytes and calls the frozen
record, candidate-anchor, and projection checks. It then runs the exact frozen
verifier against a closed compatibility projection that excludes only declared
post-V10 integration/evidence paths. Finally it verifies V1 preservation, V2-only
AST reachability, the exact runtime-reference allowlist, accepted component hashes,
reserved UI hash, live-hook hashes, and the V2/root manifests.

The compatibility projection is explicitly secondary evidence. The immutable E6
record remains the primary evidence for the historical unwired state.

## Results

- Focused V2 plus transition suite: 24 passed, 0 failed.
- Transition-aware cumulative Phase 5 suite: 2,383 passed, 0 failed, with seven
  historical current-state assertions deselected because they intentionally say
  that later integration/UI surfaces do not exist; their frozen bytes and original
  meaning remain verified by the transition gate.
- Ruff and Python compilation: pass.
- 100 authorize/consume/local-read iterations: p50 5.8298 ms, p95 14.2426 ms,
  maximum 20.4145 ms, and zero background-thread delta.
