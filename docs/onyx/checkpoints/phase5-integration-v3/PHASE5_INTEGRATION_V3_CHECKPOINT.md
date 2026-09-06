# Phase 5 Integration V3 transition checkpoint

Date: 2026-07-22

Status: independent V3 candidate implemented and default-off. No feature
activation, live restart, or UI/HUD modification was performed by this phase.

## V1 and V2 preservation

Rejected Integration V1 and V2 implementation, tests, verifiers, manifests,
checkpoints, and root hash manifests remain byte-for-byte unchanged. V3 neither
imports nor subclasses either predecessor. The live host imports V3 only.

## Collision semantics

Every invocation reference is sealed before argument validation. Any duplicate
or collision is checked before normalization, including valid, invalid, unknown,
and concurrent requests. A collision atomically consumes the original prepared
decision, purges all runtime/grant/prepared state, replaces the active seal with
a burned anti-replay tombstone, and emits a bounded audit. Neither the old nor
the new request can reach the catalog adapter. A second seal-state check closes
the normalization race before a decision can be prepared.

Exact authorization-to-dispatch binding still covers every material argument.
Comparison, decision consumption, state purge, and the provider-free local
adapter call form one session-locked boundary.

## Historical acceptance closures

Runtime V10, Approval Inbox V15, and Capability Nexus V32 have separate sorted
execution-closure manifests. Each manifest binds every copied path and digest and
has its own deterministic closure-root hash. Frozen acceptance verifiers and
records are unchanged.

Projection materialization reads each authoritative source through one open file
handle, checks handle metadata stability, hashes the bytes actually read, writes
those exact bytes to a nonexisting destination, flushes and fsyncs, then rehashes
every destination. The exact tree is checked before and after verifier execution;
extra, missing, or changed files fail closed. This checkpoint makes no unsupported
claim that a separate pre-copy stat eliminates concurrent-writer TOCTOU.

The V10 closure executes its frozen record, candidate-anchor, and mutable
projection checks while retaining the immutable E6 statement that V10 was
accepted unwired. V15 and V32 execute their frozen external acceptance verifiers
with parent execution disabled because the parent evidence is already bound by
their immutable accepted root/artifact manifests.

## Permission broker governance

The historical broker hash `8358ba39...` is retained by the V15/V32 accepted
evidence. The current generic integration hook hash `e37fb092...` is explicitly
classified as a governed post-acceptance transition and remains unchanged by V3.
The dashboard server generic hook also remains unchanged.

## Concurrent HUD boundary

`ui.py`, QML, Orb/HUD, and dashboard static assets belong to a separately
authorized concurrent transition. V3 does not import or depend on them and does
not adopt their current bytes.

## Reproducibility

The exact cumulative command and complete test-file list are recorded in the V3
manifest. It uses no `-k`, ignore, or deselection option; expected deselections
are zero.

## Results

- Focused V3 and transition suite: 35 passed, 0 failed, 0 deselected.
- Exact recorded cumulative suite: 230 passed, 0 failed, 0 deselected.
- Ruff and Python compilation: pass.
- 100 authorize/consume/local-read iterations: p50 7.4978 ms, p95 22.4206 ms,
  maximum 32.8626 ms, with zero background-thread delta.
- One environmental warning remains: pytest cannot write its ordinary cache
  directory, while the explicit cumulative `--basetemp` completed successfully.
