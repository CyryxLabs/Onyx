# Phase 7 Workspace Memory V1 checkpoint

Status: **E1-E5 candidate ready; E6 pending; default-off and not live**

Date: 2026-07-23

## E1 — scope and entry

The candidate binds the exact accepted Phase 6 exit manifest, record,
metadata, and acceptance anchor. Enabled construction fails closed if that
entry root drifts.

V1 includes only pre-ranking, read-only workspace memory retrieval. It
excludes metadata persistence, credential/profile/artifact aliases, approved-
source registry, Company Graph, contradiction/supersession writers, Founder
Brief, UI/dashboard/startup wiring, remote disclosure, and all mutation.

## E2 — capability delta

The live capability matrix and `CAPABILITY_DELTA_SNAPSHOT.md` record:

- workspace-scoped memory retrieval: `NOT_IMPLEMENTED` to `PARTIAL`;
- layered authoritative writes: unchanged `NOT_IMPLEMENTED`;
- Company Graph: unchanged `NOT_IMPLEMENTED`;
- Founder Brief: unchanged `NOT_IMPLEMENTED`.

## E3 — verification

- Platform: Windows 11 `10.0.26200`, x64
- Python: CPython 3.13.7 x64
- Selected files: 5, each in a fresh Python process
- Direct result: **77 passed, 0 failed, 0 errors**
- Subtests: **73 passed**
- Skip: **1 explained platform skip** — FIFO creation is unavailable on
  Windows in `test_workspace_registry_audit.py`
- Ruff lint: passed
- Ruff format: passed
- Python byte compilation: passed

The exact selection and per-file counts are in `cumulative-selection.json`.

## E4 — safety and rollback

Focused tests prove:

- exact default-off return before entry-root or host-binding validation;
- sealed construction and non-legacy explicit workspace identity;
- accepted Phase 6 entry-root rehash;
- workspace/principal/sensitivity/validity/freshness filtering before ranking;
- zero leakage from a higher-scoring other-workspace record;
- approved/available-only retrieval and stale labeling;
- duplicate JSON, HMAC forgery and content-digest denial;
- ambiguous cross-workspace ownership exclusion;
- workspace/sidecar/memory binding drift denial;
- read-only database hashes and no global `search()`/`list()` call;
- restricted sensitivity and broad query/policy denial;
- provenance, validity, exact memory hash and untrusted-data result labeling.

Rollback disables or omits `ONYX_PHASE7_WORKSPACE_MEMORY_V1`. V1 creates no
state, patches no runtime seam, changes no legacy API and requires no restart.

## E5 — package and limits

- ADR: `ADR-0029-phase7-workspace-memory-v1.md`
- API: sealed feature gate, query/result records, signed metadata builder,
  metadata identity helper, read-only adapter factory
- Schema migration: none; V1 uses existing `memory_metadata.payload_json`
- Network/provider/process/live calls: zero
- Persistent writes: zero
- Resource bound: 10,000 metadata rows, 2,000 query characters, 50 results,
  400 IDs per ambiguity-check SQL chunk
- Data boundary: restricted content is never retrievable; returned content is
  labeled untrusted

## E6 — pending

This checkpoint does not accept itself. Until a separate acceptance envelope
reproduces the frozen manifest and cumulative selection:

- Workspace Memory V1 remains a default-off candidate;
- Phase 7 is not exited;
- Company Graph and Founder Brief remain unimplemented;
- no live runtime authority is added;
- the full Onyx PRD remains incomplete.
