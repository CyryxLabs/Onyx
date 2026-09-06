# Phase 11 External Coding-Agent Adapter V1

> **VERSION-BOUND DESIGN BASELINE — NOT CURRENT RELEASE STATUS.** This file
> documents the V1 fail-closed adapter contract. See
> [`CURRENT_RELEASE_STATUS.md`](../CURRENT_RELEASE_STATUS.md) for current
> packaged/runtime evidence.

Date: 2026-07-31  
Status: `HEALTH_ONLY_FAIL_CLOSED` in the source tree. The installed Claude Code
CLI can be authenticated for a health probe, but its current protocol does not
return an authenticated, execution-bound account receipt. Live billable
dispatch is therefore unavailable by design. No billable-provider mission is
claimed.

## Provider selected from host evidence

V1 discovers the official Claude Code CLI for a non-billable health probe only
when all of the following are true at activation time:

- `claude` resolves to an absolute regular file;
- `claude --version` succeeds;
- `claude auth status` reports `loggedIn=true`;
- the executable SHA-256, stable Windows file ID and a non-secret
  account-binding SHA-256 remain exact.

The inspected host had Claude Code `2.1.220`, authenticated through
`claude.ai`. The CLI binary SHA-256 was
`af5bf1f1b2aadffc768eccd787084c6fdf9ba81624cbe96c1c6d9ac1a1550231`
and its Windows file ID was `4c780cdb:004000000001af7f`. This proves only
health-time authentication. Because the CLI does not bind an authenticated
account receipt to the same invocation that could incur cost,
`billable_dispatch_available=false` and Phase 11 refuses mission creation.
Codex was not selected because the WindowsApps executable could not be launched
from the subprocess boundary. GitHub CLI is never a coding provider or
publishing path in V1.

V15 does not trust `PATH` for Git. It accepts only
`C:\Program Files\Git\cmd\git.exe` with the explicit SHA-256 allowlist entry
`34a408843194be320d8a87a3c12cd5c7d2e08d03b24567a41db32e21d12569d2`.
The inspected Git file ID was `4c780cdb:0002000000113d63`.

## Authority and execution path

1. `mission_create` materializes one
   `external_coding_agent_dispatch_v1` MissionStore step.
2. The host captures the exact clean repository commit and owner-worktree
   digest. Context is generated only through the pinned Git executable from
   `ls-tree`/`cat-file` blobs in that commit. Live, ignored and untracked files
   are never context. The signed envelope binds the canonical blob manifest
   digest and count.
3. The task is written before approval only as an AES-GCM artifact. MissionStore
   and the immutable binding contain its digest, size and protected reference,
   never the source packet or credentials.
4. `ExternalAgentEnvelopeV1` HMAC-binds mission, workspace, repository commit,
   blob manifest, owner state, allowed roots, the absolute Git path plus its
   binary hash, stable file ID and file identity,
   provider/version/binary/file-ID/account, model, cost,
   wall-clock/output budgets, task, approval digest, optional prior patch
   artifact digest and expiry.
5. One normal MissionStore exact-plan approval authorizes the one dispatch.
6. Onyx materializes a no-remote clone solely from the approved commit blobs
   under `WindowsTrustedDirectoryV1`. Building clones are handle-renamed and
   crash-orphaned builds are quarantined. Every terminal clone is also
   handle-renamed to a terminal quarantine name. Terminal and crash-orphan
   roots share one retention cap of eight; reaching the bound blocks new
   materialization. The `mission_external_agent_cleanup` tool is
   `always_confirm` and performs bounded handle-relative removal. No path-based
   recursive delete exists.
7. For a future provider that supplies an authenticated execution-bound
   account receipt, the bounded packet is sent over stdin. The child environment omits
   Anthropic/GitHub credential variables so the already-authorized
   provider session is used. Safe mode, strict empty MCP
   configuration, an empty tool set and `--no-session-persistence` are forced.
   The provider can neither read nor write local files and returns only
   JSON-schema-constrained patch text.
8. Onyx obtains patch paths from Git plumbing (`git apply --numstat`), decodes
   Git C-quoted/octal UTF-8 paths, validates every canonical path, runs
   `git apply --check`, applies only
   inside the materialized clone and performs reverse-apply verification, then
   rechecks Git/provider identity and the owner repository. Git discovery is
   ceiling-bounded at the trusted state root so a clone nested below another
   repository cannot inherit the parent repository's authority.
9. The patch is retained as an encrypted `draft_pr_handoff` artifact. V1 has no
   commit, push, merge, deploy, GitHub call or pull-request creation method.

For every Git or provider subprocess, Onyx opens the executable and every
lexical ancestor without resolving reparse points, rejects reparse ancestors,
and holds deny-write/delete authority while hashing the executable from that
same handle. Hashes are recomputed on every open; there is no cross-open cache.
Windows children start suspended. After Job assignment and before
`ResumeThread`, Onyx queries `QueryFullProcessImageNameW`, independently opens
that exact child image deny-write/delete, and compares its volume/file ID and
SHA-256 to the approved held image. Both handles remain held until process
exit. Query, open or identity mismatch terminates before resume.

## Failure and recovery semantics

- Durable `attempted_unknown` intent is written before starting the CLI.
- A create-once HMAC reservation is atomically written under an interprocess
  lock before clone/provider work; it reserves both rolling rate and maximum
  cost and prevents restart double-dispatch.
- Any existing intent or receipt permanently blocks automatic redispatch.
- Missing execution-bound account receipt, timeout, cancellation, output
  limit, provider failure, account drift,
  binary drift, owner drift, out-of-scope patch and rate exhaustion fail
  closed.
- Windows dispatch is assigned to a kill-on-close Job Object. Phase 11 appends
  the durable kill event before terminating the provider process tree.
- Restart authenticates the checkpoint and receipt. A late result after
  kill/cancel cannot commit mission success.
- Follow-up is a new MissionStore mission and approval that cites only the
  prior encrypted patch artifact digest. No provider session ID, resume,
  persistence or continuity semantics exist.
- Genuinely empty output terminates as explicit `no_change`;
  it creates neither a patch artifact nor a `draft_pr_handoff`.
- A non-empty patch for which Git plumbing yields no canonical path is a
  contract failure, never `no_change`.
- Four dispatch intents per rolling 60-second window is the V1 host rate
  ceiling. The per-call host budget is USD 1.00, 900 seconds and 512 KiB.

## Verification performed

Warnings-as-errors focused tests:

- `tests/test_external_agent_adapter_v1.py`
- `tests/test_phase11_external_agent_v1.py`

The focused adapter/Phase 11 suite passed `31/31`; the V15/onboarding suite
passed `18/18` in the project virtual environment. These cover
envelope/blob/Git-identity/file-ID tamper, exact-commit-only context,
encrypted trusted-state artifacts, owner immutability, clone-only patching,
out-of-scope refusal, restart/no-retry, orphan quarantine, cancellation,
timeout/output limit, concurrent atomic rate reservation, provider drift,
execution-receipt refusal, quoted Unicode/space paths, terminal retention,
`no_change`, prior-artifact follow-up authority and host budget refusal.

The live probe executed only `--version` and `auth status`; it did not execute a
paid Claude task. No external PR creation, installed-package mission,
macOS/Linux run, E6 review or clean-machine validation is claimed.
