# Onyx Live Activation V6 — Candidate Checkpoint

Status: **CANDIDATE READY FOR INDEPENDENT GATE — NOT LIVE**

V6 preserves every V1-V5 byte. It composes V5 for its exact PCM MIME,
provider-lifetime containment, and sole setup projection, then atomically
replaces four rejected seams. The installation performs 22 reversible writes:
18 inherited V5 writes followed by four V6 writes.

## Tool-call identity and replay window

- Identity is solely the exact, non-empty provider `call_id`.
- The first observation binds the exact tool name and SHA-256 digest of
  canonical JSON arguments to that ID.
- The same ID with a different name or argument digest is refused without
  execution, including while the first call is still in flight.
- Concurrent exact duplicates share one task and receive independent copies of
  the same digest-verified immutable result snapshot, or the same frozen error
  descriptor. The underlying action runs once, and caller mutation cannot alter
  the retained result.
- The registry retains at most 256 total records, including inflight records.
  Settled records are bounded LRU tombstones; inflight records are never
  evicted. If all 256 records are inflight, a 257th new ID fails closed.
- The replay guarantee is explicitly the most recent 256 retained IDs. Once a
  settled ID is evicted from that bounded window, a later observation is a new
  call. This makes retention finite and auditable instead of claiming
  unbounded process-lifetime memory.

## Provider circuit authority

- Every state transition (`begin_attempt`, `record_failure`, `record_stable`,
  `manual_recovery`) is async, serialized by one lock, and asserts the owning
  event-loop identity.
- UI recovery never mutates circuit state. It submits one coroutine to the
  owning loop and waits for an immutable acknowledgement.
- Dashboard recovery awaits the same loop-owned command directly.
- Retry delays, cooldown, jitter, stable-close time, open threshold, and replay
  capacity reject booleans, wrong numeric types, zero/negative values,
  `NaN`, positive/negative infinity, overflow-sized integers, and values above
  hard maxima.
- Hard maxima are 300 seconds per retry delay, 900 seconds cooldown, 30 seconds
  jitter, 900 seconds stable close, and 64 consecutive failures.

## Preserved V5 behavior

- All PC and phone PCM is normalized to `audio/pcm;rate=16000`.
- `1007` audio contract failures, `1011` availability failures, network faults,
  and credential faults remain distinct.
- Gemini outages do not terminate the local HUD, dashboard, missions, or
  process.
- Commands are not buffered during provider outage.
- Only one setup overlay is visible; the V5 renderer suspends and resumes.

## Candidate evidence

- V6 focused pytest: `6 passed`.
- V4 acceptance + V5 + V6 cumulative pytest: `35 passed`.
- V6 host gate: 22/22 installation failpoints, exact rollback, exact-ID
  conflicts, canonical argument binding, concurrent single-flight success and
  error, 1,000 sequential IDs, 256 retained records, 744 evictions, and 257th
  all-inflight refusal.
- Numeric adversarial gate: boolean, zero, negative, `NaN`, `+Inf`, `-Inf`,
  overflow integer, and hard-maximum violations refused.
- Recovery authority gate: a real worker thread submitted recovery, waited for
  the owner-loop acknowledgement, and direct transition from a different loop
  was refused.
- Fake-provider E2E: `1007`, then `1011`, then automatic recovery on attempt 3;
  601 accelerated seconds; exact MIME on every attempt; one dashboard/listener
  start; V5 HUD/process alive; zero setup prompts.
- Real offscreen Qt: one visible setup surface and renderer suspend/resume.
- Ruff, py_compile, and cumulative verifier passed.
- No real provider/network call and no live activation were performed.

## Gate boundary

This checkpoint is candidate evidence, not production evidence. A separate
independent gate must verify the manifest and rerun the complete V6 suite before
any controlled live activation. External Gemini availability remains unproven
until that later live step.

## Candidate controls

- Active candidate: `scripts\launch_onyx_live_v6_active.cmd`
- Exact rollback: `scripts\launch_onyx_live_v6_rollback.cmd`
- Preflight: run `scripts\launch_onyx_live_v6.pyw --preflight-only` with the
  complete canonical V6 activation environment.
