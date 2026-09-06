# Phase 11 Executable Sandbox V1

> **VERSION-BOUND DESIGN BASELINE — NOT CURRENT RELEASE STATUS.** This file
> documents the V1 authority and recovery contract. Consult
> [`CURRENT_RELEASE_STATUS.md`](../CURRENT_RELEASE_STATUS.md) for the current
> packaged/runtime evidence and unresolved release gates.

## Status and activation

`core/phase11_executable_sandbox_v1.py` is a local, default-off successor
candidate live-wired through the exact `ExecutableSandboxHostV1` and exact
enabled `Phase11ExecutionLedgerV1`. `recovered_receipt` accepts only the exact
ledger-authenticated canonical receipt for the original
mission/execution/attempt and never redispatches. Real Docker execution,
rebuilt/installed package evidence and independent E6 remain unproved.

The feature flag is `ONYX_PHASE11_EXECUTABLE_SANDBOX_V1`; only the exact
lowercase value `true` enables it. An explicitly supplied empty environment
does not fall back to the process environment. Disabled construction performs
no path lookup, Docker call, directory creation, or key validation.

Enabled construction requires:

- an absolute trusted Docker CLI path;
- an explicitly pinned local endpoint: Windows
  `npipe:////./pipe/<name>` or a POSIX `unix:///absolute/socket`;
- an explicit platform equal to `linux/amd64` or `linux/arm64`;
- existing trusted control and clone-parent directories;
- a receipt/digest key of at least 32 bytes.

Remote `tcp`, `ssh`, and HTTP endpoints are refused. Every image inspect,
container run, container inspect, and cleanup command contains the pinned
`--host` argument; Docker context selection is never inherited.

## Input and clone authority

Requests are runtime type checked. They contain a bounded mission identifier,
an exact lowercase `sha256:<64 hex>` image ID, a non-empty `tuple[str, ...]`,
a finite timeout no greater than 300 seconds, and an integer output limit no
greater than 2 MiB. Booleans are not accepted as numeric limits.

The clone must be an existing direct child of the configured clone parent.
The CLI, trusted roots, and clone are checked for symlink/reparse components.
On POSIX, trusted roots, the clone root, and every clone descendant must be
owned by the current effective user and not be group/world writable. On
Windows, both roots, the clone root, and every descendant must resolve beneath
the current user's resolved `LOCALAPPDATA` tree, be owned by an approved
principal, and have a non-null DACL that grants no write/modify/full-control
ACE to principals other than the current user, SYSTEM, Administrators, Creator
Owner, or Owner Rights. Standard and object access-allow ACEs are evaluated
using their final trustee-SID tuple element. Callback, callback-object,
compound, and unknown allow/ACE variants fail closed; only explicitly
recognized deny/audit types are ignored. Later same-user owner/DACL changes
remain part of the same-user TCB. Filesystem identities for the roots and
clone are recorded and rechecked immediately before `docker run`.

The sandbox also builds a bounded keyed manifest of the clone (at most 20,000
entries and 512 MiB of regular-file content). It hashes relative paths,
metadata, and file bytes. Descendant symlinks/reparse points, special files,
hardlinks, and entries crossing the clone root's device are refused. Open-file
identity is checked around each read, and the complete manifest is recomputed
immediately before launch. Both declared size and actual bytes read are capped
at 512 MiB. Directory enumeration is never materialized without a bound:
scandir entries are counted with cancellation/deadline checks and collection
stops before more than 20,000 can be appended, after which the bounded list is
sorted. Each manifest pass has a 30-second deadline and checks cancellation
during traversal and file reads. A mismatch fails closed.

There is necessarily a small path-based bind-mount race between the final host
check and Docker opening the source. Mutation by another process running as
the same OS user after the prelaunch manifest is outside this V1 threat model.
Observed identity or manifest drift before launch fails closed; preventing a
malicious same-user race after the final check requires a future
handle/identity-bound staging API.

## Local immutable image rule

The sandbox runs a full local `docker image inspect <exact-id>`. The observed
ID must equal the requested ID, the image's `Os` field must be exactly `linux`,
and `Architecture` must match the configured `amd64` or `arm64`; missing,
malformed, Windows, or mismatched image metadata fails closed.
`Config.Volumes` must be absent/null; any declared value is refused, preventing
Docker from creating an implicit writable anonymous volume (for example Redis
`/data`).

Execution repeats the exact ID and uses `--pull never --platform` with the
exact configured `linux/amd64` or `linux/arm64` value. There is no pull or
build path. `--no-healthcheck` prevents image health checks.

## Container confinement

The only host mount is:

```text
type=bind,source=<controlled-clone>,target=/workspace,readonly,bind-propagation=rprivate,bind-recursive=disabled
```

Fixed controls also include network `none`, a read-only root filesystem, all
capabilities dropped, `no-new-privileges`, numeric user `65532:65532`, pids
64, `--memory 256m --memory-swap 256m` (256 MiB total memory plus swap, so
Docker cannot add swap beyond that total), one CPU, a bounded
`noexec,nosuid,nodev` `/tmp`, fixed non-secret container environment, and
`shell=False` for every host command. No Docker socket, device, secret,
additional host directory, or volume is mounted.

Docker logging is explicitly disabled with `--log-driver none`, preventing
raw test output from being persisted by the daemon's configured default log
driver.

## Lifecycle, ownership, and collision controls

At most four executions may be active. In addition to the bounded in-process
counter, four persistent control-root slot files carry non-blocking OS-held
locks, enforcing the aggregate limit across processes. Slot locks are released
by the OS if a process dies. Admission acquires the in-process and OS-held slot
before either clone-manifest pass. Every validation, cancellation, deadline,
Docker, and cleanup failure closes the slot stream and releases the in-process
count even if explicit unlock itself fails. Random token generation, clock
initialization, and all other post-admission work are inside the same
lease-finalization boundary. A mission-lock unlink or OS-unlock failure is
normalized at the public boundary to `SandboxCleanupError`; a simultaneous
execution failure is preserved as its explicit cause, while a release-only
failure carries the raw release error as its cause. Each mission also acquires
an atomic keyed-name lock file beneath the trusted control root, denying a
same-mission collision from another process.

Normal release deletes the lock file. A hard crash can leave a stale lock; V1
fails closed until an operator, after confirming no execution owns that
mission, removes the stale file. If initial lock writing or closing fails, V1
removes only the lock it just created and releases its in-process slot; it
never removes a pre-existing colliding lock. No cidfile is created.

Container names have 128 random bits. Each run has an independent 256-bit
ownership token in a fixed Docker label. Finalization always:

1. inspects the random name;
2. treats Docker's explicit “no such container/object” result as idempotent
   success;
3. otherwise verifies the exact ownership label and reads the immutable
   64-hex container ID;
4. runs `rm --force --volumes <container-id>`;
5. re-inspects the ID and requires explicit absence.

A label mismatch fails without deletion. Cleanup failure after another error
is raised with the original failure preserved as its cause. Timeout,
cancellation, output overflow, and stuck output paths terminate then kill the
Docker CLI if necessary and prove that it exited; an unkillable CLI fails
closed.

## Receipt privacy and integrity

Stdout and stderr have fixed independent portions of the requested combined
budget. This makes accepted bytes and their digests independent of pipe read
chunking and stdout/stderr scheduling. Overflow fails closed.

The receipt contains byte counts, result metadata, the exact image digest,
keyed HMAC-SHA-256 values for mission ID, argv, the authenticated clone
manifest (`prelaunch_clone_manifest_hmac_sha256`), stdout, and stderr, plus an
HMAC-SHA-256 signature over the canonical complete receipt. It never contains
the key, raw output, clone path, mission ID, random container name, or
ownership token. The keyed values prevent dictionary recovery without the
caller-held key.

## Trust boundary and optional smoke

This boundary trusts the local Docker CLI, the explicitly selected local
Docker daemon, the Linux-container runtime/VM, the host OS, and other
processes running as the same OS user. Docker is a privileged local authority;
this module limits one test workload but is not a hostile-host boundary.

## Live-wired successor candidate

The current default-off V15 candidate is live-wired through
`Phase11LiveMissionV1` only when the complete executable flag group, exact
official `ExecutableSandboxHostV1`, allowlisted image and host key are present.
`ProjectAutopilotV1` accepts no caller sandbox factory. Its limited process
adapter receives Docker argv and bounded process options, never the signing key
or the exact enabled `Phase11ExecutionLedgerV1` injected into the official
sandbox.

The ledger records intent and dispatch reservation before execution and the
authenticated canonical receipt after completion. `recovered_receipt` accepts
only that exact committed mission/execution/attempt receipt. Missing, modified
or foreign evidence remains `attempted_unknown`; cancel-before-launch creates
no dispatch, and recovery never retries or redispatches.

This is a local candidate, not E6. No real-Docker run, rebuilt/installed
package, external monotonic rollback anchor, retry/takeover authority or
clean-host acceptance is claimed.

The normal suite is dependency-injected and does not require Docker:

```powershell
python -m pytest -q tests/test_phase11_executable_sandbox_v1.py
```

The opt-in real smoke never pulls or builds:

```powershell
$env:ONYX_PHASE11_DOCKER_SMOKE = "1"
python -m pytest -q tests/test_phase11_executable_sandbox_v1.py
```

It proves that the already-local pinned Redis image
`sha256:6ab0b6e7381779332f97b8ca76193e45b0756f38d4c0dcda72dbb3c32061ab99`
is rejected because it declares `/data`. When the already-local pinned Mailpit
image
`sha256:37a38e48e9338cd7e89dfeb487f37b02ebfcd9cb23111bed2d345e79d37d6dd6`
is available, it provides the no-volume PASS smoke. A missing exact image
fails closed; the test does not substitute a tag.
