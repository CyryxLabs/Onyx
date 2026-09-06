# ONYX-GWS-1.3.0 - Frozen Provenance and Packaging Integration

## Status

**Draft**

## Blocked

**NOT READY for implementation.** PO has declared Draft 0.2 definition READY and
Architecture has declared the story ready/GO, but both explicitly retain NO-GO
for implementation. The packaging surfaces that this story must change already
contain unrelated modified or untracked work in the current checkout:

- modified: `packaging/onyx.spec`, `scripts/build_release.py` and
  `docs/INSTALLATION.md`;
- untracked: `scripts/package_hygiene.py`, `scripts/bootstrap_onyx.pyw`,
  `core/onyx_live_activation_google_workspace_v1.py`,
  `scripts/bootstrap_onyx_live_google_workspace_v1.pyw` and
  `scripts/launch_onyx_live_google_workspace_v1.pyw`.

No implementation agent may overwrite, normalize, stage, clean or otherwise
absorb those bytes. A normal Git worktree is insufficient because the accepted
GWS 1.0-1.2 baseline contains untracked files. Implementation may begin only
after either:

1. the owner supplies a read-only, content-addressed isolated candidate that
   contains every accepted GWS 1.0, 1.1 and 1.2 source, test, story, provenance
   manifest and packaging input, with an exact inventory, per-file hashes and a
   reproducible candidate root; or
2. the owner explicitly authorizes overwrite of each dirty surface listed
   above and the resulting complete candidate is immediately snapshotted into
   that same content-addressed form before implementation.

The candidate inventory and root must be recorded in this story and independently
reviewed before the first product edit. The candidate record must also name the
exact normalized package-relative frozen-manifest path for each PyInstaller
Analysis/executable, at minimum `Onyx.exe` and `Onyx-GoogleWorkspace.exe`; a
shared, implicit or inferred path is not accepted. Neither path authorizes Git,
build, installation, provider, deployment or release work.

## Standalone Continuation

This story is a standalone continuation of
[ONYX-GWS-1.2.0](./ONYX-GWS-1.2.0.md). No parent epic is currently recorded.
The link provides traceability only; it does not inherit Gate B or Gate C.

## Executor Assignment

```yaml
executor: "@dev"
quality_gate: "@architect"
quality_gate_tools:
  - source-versus-frozen trust-boundary review
  - stable-bootstrap default-off and dual-flag selection tests
  - package-staging and development-payload hygiene tests
  - packaged-helper contract and provider-free smoke tests
  - independent adversarial QA and lifecycle review
```

## Story

**As the** Onyx owner,  
**I want** the source-approved Google Workspace activation converted into an
explicit, production-only frozen provenance and package-selection contract,  
**so that** a later Windows candidate can include the exact governed GWS runtime
without distributing tests, stories or build tooling and without changing the
default V24 behavior when GWS is not selected.

## Problem Statement

`ONYX-GWS-1.2.0` is Done only for source-only Gate A. Its authenticated source
session intentionally binds repository material that a production package must
not ship: two tests, two stories, the source CLI and a broad 704-module checkout
closure under `actions`, `core`, `dashboard`, `memory` and `scripts`. The current
package stages all top-level `core/*.py` but only a narrow script allowlist, and
its hygiene contract rejects tests and `build_*` scripts. The stable desktop
bootstrap selects V24 only, the GWS bootstrap/launcher are not staged, the
PyInstaller spec has no GWS helper executable, and the existing native startup
smoke does not emit candidate-bound redacted evidence.

Copying the source closure into the bundle or weakening hygiene exceptions would
either fail activation or leak development payload into the product. This story
must instead establish a distinct frozen authority tied only to the productive
bytes actually staged, while retaining the complete source authority unchanged.

## Dependency and Evidence Boundary

- `ONYX-GWS-1.2.0` remains **Done — Source-only Gate A Approved**. Its policy,
  receipts, idempotency, audit, lifecycle, rollback and source provenance
  assertions cannot be weakened or reclassified.
- The current installed product is Onyx 1.1.9 V31 and contains V23, not V24 or
  the GWS branch. This story makes no installed-product claim.
- The accepted seven-dependency aggregate remains
  `0502ad2243d1d4b8d23fd032ccd0c4cff0c58c9940c0c635cd10228e664fecce`.
  It must remain byte-identical and independently reverified. It is not the
  complete v1.2.6 closure, a frozen/package provenance root or a claim that the
  successor is cryptographically identical to v1.2.6.
- The v1.2.6 source closure currently contains 704 modules with root
  `2e79471dc9e8e3a27be114f89e98e02a95c72ff2bf90b560e6e3f5a154b1605b`.
  This story necessarily changes members of that closure. The implementation
  must therefore define a new content-addressed **v1.3 source-successor
  closure**, record its exact member count and root after all edits, and obtain
  fresh independent Architecture and QA review. Only the seven-dependency
  aggregate and v1.2.6 functional/security invariants are preserved; the old
  704-module root must not be reported as the successor root.
- Gate B Git/pre-PR provenance is still open. Gate C build, ZIP, Setup,
  installation, upgrade, rollback, provider, signing, clean-host and release
  evidence are explicitly deferred.
- Source test success under this story proves only that package inputs and
  contracts can be assembled deterministically. It does not prove that a
  PyInstaller artifact was built or that any installed/provider path works.

## Goals

1. Preserve the complete v1.2.6 source-mode trust and execution behavior.
2. Define a separate frozen provenance authority over the productive staged
   closure only.
3. Add the GWS bootstrap/launcher and productive dependency closure to package
   staging without adding tests, stories, source-only evidence or build scripts.
4. Make the stable bootstrap select GWS only when a GWS flag occurrence is
   present, while both flags absent continue through the exact V24 path without
   reading or importing GWS files.
5. Define the Windows packaged helper and an explicit, redacted, provider-free
   diagnostic contract suitable for later candidate-bound Gate C evidence.
6. Prove all changes with source-level staging, selector, manifest, hygiene,
   security and lifecycle tests only.

## Non-Goals

- Building PyInstaller, ZIP, Setup or any other distributable.
- Installing, upgrading, uninstalling or replacing the current Onyx product.
- Creating shortcuts, registry/autostart entries or persistent owner selection.
- Provisioning real owner credentials, opening a browser, performing OAuth or
  calling Gmail, Calendar, DNS or any provider endpoint.
- Testing a real frozen executable, installed tree, signed artifact or clean
  machine.
- Granting Gate B, Gate C, deployment, release or provider acceptance.
- Adding macOS or Linux GWS support. GWS remains Windows-only until separate
  native vault, OAuth and host acceptance exists for each platform.
- Modifying V24, its versioned bootstrap/launcher, its declaration set, or the
  installed V31 tree.
- Relaxing any v1.2.6 policy, scope, audit, receipt, idempotency, redaction,
  lifecycle or rollback assertion.

## Required File Surfaces

| Surface | Source-only change allowed by this story | Required invariant |
|---|---|---|
| `core/onyx_live_activation_google_workspace_v1.py` | Add an explicit `sys.frozen` authority split, successor-source closure and frozen-manifest authority | Preserve the seven-dependency aggregate and every v1.2.6 functional/security invariant; record a new successor count/root; no second live controller |
| `core/google_workspace_packaged_provenance_v1.py` (new) | Encapsulate the closed frozen-manifest schema, canonicalization, raw digest check, captured-byte closure and continuous finder/health fence | Its compiled code authority and expected raw manifest digest are authenticated before it interprets the manifest; it cannot duplicate runtime policy/lifecycle logic |
| `scripts/package_hygiene.py` | Stage the GWS bootstrap, launcher, helper entrypoint and manifest-declared productive closure; generate/verify the frozen manifest | No new GWS tests, stories, source-only manifest, `build_*` scripts or broad compatibility exception; preserve the three historical sealed V24 test inputs |
| `packaging/onyx.spec` | Declare GWS dynamic modules and staged `actions`, `memory` and required Python `dashboard` content; compile Analysis-only `core._google_workspace_frozen_authority_v1`; define the Windows `Onyx-GoogleWorkspace.exe` helper target | The authority module is compiled-only, not staged data; `google.genai` alone is not GWS integration; helper is Windows-only and CLI-first |
| `scripts/bootstrap_onyx.pyw` | Before POSIX selection, detect any case-insensitive occurrence of either GWS flag and route that environment to the GWS bootstrap | Both flags absent execute the existing V24 selection with zero GWS file/import/config access |
| `scripts/bootstrap_onyx_live_google_workspace_v1.pyw` | Support source and frozen roots while retaining strict pair validation, authenticated launcher selection and sanitized failures | Only the exact canonical pair with exact value `true` enables GWS; partial/malformed/alias input fails closed |
| `scripts/launch_onyx_live_google_workspace_v1.pyw` | Add an explicit provider-free packaged diagnostic argument and redacted JSON receipt | Existing runtime cleanup and three bounded rollback attempts remain authoritative |
| `scripts/onyx_google_workspace_packaged_v1.py` (new) | Expose the approved configure/status/connect/disconnect/test operations and explicit canonical launch path without depending on the source CLI | Reuse the single controller and broker; no raw-host consequential shortcut, model-visible tool duplication, secret output or provider call in this story's tests |
| `scripts/build_release.py` | Add source definitions and testable helper functions for later baseline flag sanitization and GWS smoke evidence binding | This story does not execute a build; aliases/casing of GWS flags must be removed from baseline smoke environments |
| `docs/INSTALLATION.md` | Draft Windows-only, default-off, helper, scope and later lifecycle instructions, clearly labelled unavailable until later Gate C acceptance | Must not claim an artifact exists or is operational |
| Tests under `tests/` | Add isolated selector, staging, spec, provenance, helper, smoke, security and rollback contract coverage | Existing v1.2.6 assertions remain unchanged and green |

Architecture accepted the exact provenance and packaged-helper paths shown in
this table. That path decision does not grant overwrite authority for the
current dirty checkout or make Draft 0.1 ready for implementation.

## Source and Frozen Authority Contract

### Source mode

When `sys.frozen` is false, the seven-dependency manifest and fixed aggregate
remain byte-identical and are reverified before enabled GWS imports. The
captured-source finder, continuous health fence, authenticated V24/V23 chain,
policy, audit/idempotency stores and rollback semantics remain functional
invariants.

The full 704-module v1.2.6 root cannot remain identical because this story edits
members of that closure. Source mode therefore creates a versioned successor
closure from the content-addressed isolated candidate. The implementation must
record the exact successor member list, member count and root, verify it before
enabled imports, fence it continuously, and obtain independent Architecture and
QA review of that new root. It must never label the successor as the old
704-module/root identity. A frozen manifest cannot substitute for or weaken
either the fixed seven-dependency authority or the successor-source authority.

### Frozen mode

When exact built-in `sys.frozen is True`, activation rejects source manifests as
runtime authority and authenticates a versioned frozen manifest containing only
the productive first-party closure distributed for that executable/Analysis.

### Closed typed frozen-manifest schema

The UTF-8, no-BOM JSON document is a closed object: unknown or missing keys,
duplicate JSON keys, non-built-in values, floats, `null`, booleans in integer
fields and integer overflow are rejected. Its exact top-level members are:

| Field | Exact type and rule |
|---|---|
| `schema` | built-in string exactly `onyx.gws.frozen-productive-manifest.v1` |
| `manifest_version` | built-in integer exactly `1` |
| `target` | built-in string exactly `windows-x86_64` |
| `analysis_id` | non-empty lowercase ASCII identifier matching `[a-z0-9][a-z0-9._-]{0,63}` |
| `predecessors` | closed object with lowercase 64-hex `v24_sha256` and `v23_sha256` |
| `entrypoints` | closed object with lowercase 64-hex digests for `stable_bootstrap`, `gws_bootstrap`, `gws_launcher`, `gws_activation` and `packaged_helper` |
| `entries` | non-empty built-in list of closed entry objects |
| `closure_count` | built-in integer equal to `len(entries)`, range `1..10000` |
| `closure_root_sha256` | lowercase 64-hex root computed by the algorithm below |

Each entry is a closed object containing exactly:

- `path`: built-in string in Unicode NFC, relative, forward-slash-separated,
  with no backslash, drive/UNC prefix, empty/`.`/`..` segment, control/format
  character or trailing dot/space segment;
- `module`: built-in string in NFC containing the exact import name, or the
  empty built-in string only for a non-import entrypoint/data member;
- `kind`: built-in string enum `python-source`, `entrypoint` or `data`;
- `size_bytes`: built-in integer in range `0..268435456`; and
- `sha256`: built-in lowercase 64-hex string.

Paths retain their canonical NFC casing, sort by their UTF-8 bytes, and must be
unique both byte-for-byte and by `NFC(path).casefold()` so Windows/Unicode case
collisions fail closed. Module names must map exactly to their canonical source
paths and are unique only when `module != ""`; multiple `data`/`entrypoint`
entries may use the empty built-in string. JSON canonical bytes use UTF-8, NFC
strings, lexicographically sorted object keys, no insignificant whitespace,
separators exactly `,` and `:`, and JSON escaping equivalent to
`ensure_ascii=True`.

`entrypoints` and `predecessors` are indexes over `entries`, not independent
claims. Each digest must match exactly one entry with the required canonical
path and compatible kind:

| Index field | Required `entries[].path` |
|---|---|
| `entrypoints.stable_bootstrap` | `scripts/bootstrap_onyx.pyw` |
| `entrypoints.gws_bootstrap` | `scripts/bootstrap_onyx_live_google_workspace_v1.pyw` |
| `entrypoints.gws_launcher` | `scripts/launch_onyx_live_google_workspace_v1.pyw` |
| `entrypoints.gws_activation` | `core/onyx_live_activation_google_workspace_v1.py` |
| `entrypoints.packaged_helper` | `scripts/onyx_google_workspace_packaged_v1.py` |
| `predecessors.v24_sha256` | `core/onyx_live_activation_v24.py` |
| `predecessors.v23_sha256` | `core/onyx_live_activation_v23.py` |

A missing, duplicated or digest-inconsistent cross-binding fails closed. The
candidate record binds each Analysis id to its exact manifest path and raw
digest, so a manifest from one executable cannot satisfy another Analysis.

For each entry in path order, compute:

```text
leaf = SHA256(
  UTF8(path) || 0x1f || UTF8(module) || 0x1f || UTF8(kind) || 0x1f ||
  ASCII(decimal size_bytes) || 0x1f || ASCII(lowercase sha256)
)
closure_root_sha256 = lowercase_hex(SHA256(leaf_1 || leaf_2 || ... || leaf_n))
```

The raw manifest file must already equal its canonical serialization. A
build-generated Analysis-only module with logical name
`core._google_workspace_frozen_authority_v1` is compiled inside the target's PYZ
and never staged as modifiable source/data. It is a closed constant carrier for
the schema id, Analysis id and lowercase SHA-256 of the raw manifest bytes.
Frozen activation accepts it only from the exact PyInstaller frozen loader with
exact built-in field types, authenticates it before any other GWS import and
hashes the raw manifest **before JSON decoding or importing the provenance
module**; only an exact digest match permits schema interpretation.
`core/google_workspace_packaged_provenance_v1.py` then enforces the closed
schema and closure algorithm. A staged manifest cannot authenticate itself.

### Acyclic provenance graph

The manifest contains no build-input, bundle, artifact, installed-inventory,
release or signature root because each is produced after and depends on the
manifest bytes. The only permitted graph is:

```text
frozen productive manifest
    <- build-input seal
    <- per-Analysis bundle inventory
    <- release manifest
    <- artifact signature
```

At runtime, the compiled authority pins only the raw frozen-manifest digest.
Build-input, bundle, artifact and installed roots are later external Gate C
evidence. If a diagnostic harness supplies them, the runtime receipt places
them under an explicit `untrusted_external_inputs` object with trust label
`untrusted-external-input`; it must not describe them as measured, verified or
authenticated by the runtime.

### Frozen execution authority

After raw-digest/schema/entry verification, activation captures the verified
bytes for every first-party GWS lifecycle module and installs one authoritative
finder before executing the first such module. GWS first-party code must execute
from those captured bytes, not from a normal unsealed PYZ import. The finder and
continuous health fence remain authoritative through construction, dispatch,
helper command handling, rollback and shutdown. Preloaded modules, finder
precedence drift, code/path/loader drift or any first-party import not listed in
the manifest fail closed. The already authenticated stable bootstrap, GWS
bootstrap, launcher and activation are the only boot-chain exceptions, and each
is hash-bound before execution.

The productive manifest must reject missing, extra, duplicate, case-colliding,
symlink/reparse, non-regular, path-traversing or byte-drifted inputs before GWS
module/service construction. It excludes new GWS tests/stories/development
evidence, the source-only seven-file manifest, the source CLI when it is not the
packaged helper, `scripts/build_*`, caches, logs, credentials and runtime owner
data. The three historical V24/HUD test inputs already sealed by
`RUNTIME_TEST_EVIDENCE_FILES` remain exact predecessor compatibility inputs and
are neither removed nor generalized into a new GWS exception.

The frozen execution chain is exactly:

```text
stable bootstrap
  -> locally hash-authenticated GWS bootstrap
  -> authenticated GWS launcher
  -> authenticated GWS activation
  -> authenticated compiled manifest-digest authority
  -> authenticated frozen productive manifest
  -> captured-byte productive closure and authoritative finder
  -> authenticated V24/V23 predecessors
```

## Stable Bootstrap Selection Contract

The stable bootstrap must inspect environment key names case-insensitively for
any occurrence of either:

- `ONYX_GOOGLE_WORKSPACE_LIVE_V1`
- `ONYX_GOOGLE_WORKSPACE_CONNECTOR_V1`

If neither occurs, the bootstrap follows the existing platform selector. On
Windows that means the exact current V24 bootstrap; no GWS path is resolved,
opened, hashed or imported and no GWS configuration, vault, audit, directory,
thread, browser or network surface is touched.

If either key occurs in any casing, selection is delegated to the GWS bootstrap
before the POSIX selector only after the stable bootstrap reads stable regular
bytes, verifies an embedded exact SHA-256 for the GWS bootstrap, rejects
preloaded/path-swapped/link/reparse inputs and executes the captured verified
bytes. The GWS bootstrap then validates that the environment contains the exact
two canonical key names, each exactly once and with the built-in string value
`true`. One flag, aliases, case variants, whitespace, alternate values,
duplicate/conflicting sources or any other ambiguity fail closed with a
sanitized diagnostic and zero GWS/provider effect.

V24, `scripts/bootstrap_onyx_live_v24.pyw` and
`scripts/launch_onyx_live_v24.pyw` remain byte-for-byte unchanged. Default-off
tests must prove exact V24 target selection and identical V24 declaration and
startup behavior; they must not claim that the additive stable bootstrap file
itself is byte-identical.

## Productive Staging and Hygiene Contract

- Stage only the GWS bootstrap, launcher, packaged helper, frozen manifest and
  the manifest-declared productive closure.
- Include productive `actions`, `memory` and required Python `dashboard`
  modules only when present in that declared closure; do not copy entire source
  trees merely to satisfy the source-mode 704-module scan.
- Preserve the existing package-hygiene rejection of new GWS tests, stories,
  caches, logs, correction/research history, unapproved evidence and `build_*`
  scripts. Preserve exactly the three historical sealed V24/HUD test inputs in
  `RUNTIME_TEST_EVIDENCE_FILES`; do not remove them or add a new GWS test/story
  exception.
- Do not add GWS paths to `COMPATIBILITY_EXCEPTIONS` to bypass hygiene.
- Reject drift between the staged inventory, PyInstaller `datas`/hidden imports,
  frozen manifest and build-input seal.
- Define staging uniqueness per PyInstaller `Analysis`/executable: every logical
  productive member occurs exactly once inside the `Onyx.exe` Analysis and
  exactly once inside the `Onyx-GoogleWorkspace.exe` Analysis. Physical
  duplication across two one-file executables is permitted only when reported
  in both per-Analysis inventories; it is not a logical duplicate within either
  target.
- Preserve third-party distribution closure and license/SBOM discovery. Adding
  Google Workspace dependencies must be explicit; the existing `google.genai`
  collection is Gemini and cannot be cited as GWS coverage.
- Staging remains deterministic and operates only inside an explicitly allowed
  build root. No source, installed or owner-data path may be cleaned or mutated.

## Packaged Helper Design

The Windows package specification must define a CLI-first helper named
`Onyx-GoogleWorkspace.exe` from
`scripts/onyx_google_workspace_packaged_v1.py`. Its packaged entrypoint must
enter the one accepted v1.2 successor activation and reuse its single live
controller, permission broker, service, audit/idempotency store and lifecycle.
It must not invoke consequential host methods directly or copy the source CLI's
raw-host shortcut. The controller exposes one non-model helper command adapter
for:

- `configure` (native configuration and witness provisioning);
- `status`;
- `connect` and `disconnect` under the existing consequential policy;
- bounded `test-gmail` and `test-calendar`; and
- an explicit `launch` or equivalent command that starts the same `Onyx.exe`
  with the exact canonical dual flags.

`configure`, `connect`, `disconnect`, revoke and enabling/launching persistent
selection are consequential. They require an exact, fresh trusted approval
decision issued by the existing broker and bound to helper executable identity,
command, owner/workspace/account binding, canonical arguments, nonce/trace and
expiry. CLI arguments, process presence, model text, autonomous mode or a prior
approval can never synthesize this decision. Read commands retain the existing
owner-autonomy constraints and audit/idempotency semantics.

For `launch`, the helper must resolve the packaged `Onyx.exe` from its sealed
bundle inventory, authenticate its stable regular-file bytes, reject links,
path replacement and hash drift, construct a new allowlisted environment that
removes every inherited GWS flag/config alias before adding only the exact
canonical values, and spawn with an argv list and `shell=False`. A successful
spawn is not success by itself: the child must return a bounded,
HMAC-authenticated post-spawn receipt through an owner-data rendezvous proving
the expected executable digest, PID, activation profile, canonical flag pair
and initialized controller state. Timeout, mismatch or ambiguous dispatch is
`UnknownOutcome`; blind retry is prohibited.

The helper must never expose tokens, OAuth codes, PKCE material, client secrets,
owner/account/workspace identifiers, message/calendar content, filesystem
authority paths or raw exception text. It must use native vault/authority
storage and must not create a parallel credential store, tool declaration,
policy engine or live controller. Frozen helper and launcher logs are written
only beneath the existing owner-data log root resolved by `core.paths`; they
must never write under `_MEIPASS`, the executable directory, the install root or
the source tree.

This story implements and source-tests packaging integration only. Real helper
execution, configuration persistence, autostart/reboot behavior, upgrade,
uninstall and owner-data preservation are deferred to installed-lifecycle Gate
C stories. Provider-bearing commands must be replaced by explicit provider-free
fakes/fences in this story's tests.

## Provider-Free Smoke Contract

The GWS launcher must accept one explicit packaged diagnostic argument separate
from normal startup. The diagnostic must install measurable fences before host
construction so DNS, sockets, HTTP, browser launch and provider dispatch fail
the test if attempted. It may validate only frozen provenance, service
construction with disposable native configuration, declaration/policy binding,
`status`, rollback and cleanup.

It emits one JSON object to an owner-data evidence path or stdout, with an
explicit versioned schema and only redacted/candidate-bound fields:

- status (`passed` or `failed`) and classification exactly `provider-free`;
- OS, architecture and activation profile;
- runtime-measured predecessor V24 hash, pinned raw frozen-manifest digest and
  verified productive-closure root;
- a separate `untrusted_external_inputs` object for any build-input, bundle,
  artifact or installed-inventory roots supplied by a later harness, with each
  exact value labelled `untrusted-external-input`; the runtime cannot promote,
  echo or describe those values as measured/authenticated evidence;
- exact dual-flag selection result;
- booleans proving zero DNS/network/browser/provider calls;
- declaration count/name, lifecycle state, rollback attempt count and residual
  resource count;
- UTC timestamp and a stable host pseudonym; and
- receipt/event digests that reveal no owner or Google content.

The stable host pseudonym is
`lowercase_hex(HMAC-SHA256(pseudonym_key, canonical_host_binding))[:32]`.
`pseudonym_key` is a dedicated non-exportable native-vault secret created once
for the current owner/install binding only after explicit GWS provisioning; it
is reused across upgrade and process restart, never logged or returned, and is
rotated only by an explicit owner reset/rebind. Uninstall/delete/preservation
behavior remains a Gate C lifecycle decision. Source/provider-free tests use a
disposable isolated vault/key and must label the pseudonym as test evidence.
`canonical_host_binding` is a closed, versioned byte record of the native host
binding and contains no network address or owner-readable PII in the receipt.

Missing candidate identity is represented as an explicit unavailable field or
causes the relevant later gate to fail; tests may not fill identity fields with
invented hashes. A provider-free pass cannot be relabelled provider, installed
or release acceptance.

## Security and Lifecycle Invariants

1. Default-off remains zero-GWS-side-effect and exact-V24 on Windows.
2. Frozen authority cannot satisfy source mode; source authority cannot satisfy
   frozen mode.
3. Manifest verification precedes every GWS productive import, vault access,
   listener, browser, network or provider-capable object.
4. The existing single model-visible `google_workspace` declaration, strict
   five-action schema, owner/workspace/account binding, read-only scopes and
   consequential `connect`/`disconnect` policy are unchanged.
5. Existing authenticated audit, exactly-once idempotency, `Denied` versus
   `UnknownOutcome`, receipts, post-verification and redaction remain mandatory.
6. Package/helper diagnostics cannot weaken policy or synthesize trusted
   approval.
7. Startup publication remains transactional. Failure retains cleanup authority
   and unregisters only GWS-owned state.
8. Normal and exceptional shutdown close only GWS-owned service, executor,
   audit, listener, lease and source/frozen provenance resources.
9. Launcher cleanup preserves the primary sanitized failure and performs up to
   the existing three bounded rollback attempts; cleanup-pending is secondary
   evidence, never success.
10. No code in this story deletes or mutates system files, the installed V31
    tree, owner data or credentials.
11. No test accesses a real Google account, real owner vault entry, browser,
    network or provider.
12. Evidence fields and exception topology are scanned for credentials, PII,
    message/calendar content, raw paths and unredacted provider errors.
13. Frozen logs and post-spawn rendezvous files exist only under owner-data,
    apply restrictive owner-only permissions, contain no secrets/content and
    are cleaned through the controller-owned lifecycle; `_MEIPASS`, install and
    source roots remain read-only.

## Acceptance Criteria

1. The exact eight dirty surfaces in Blocked remain recorded. Dev performs no
   implementation until a read-only content-addressed isolated candidate
   containing every accepted 1.0-1.2 source/test/story/manifest/package input is
   inventoried with per-file hashes and a reproducible root, or explicit
   per-surface overwrite authority is followed immediately by that same
   snapshot. The record names the exact manifest path and raw digest for each
   Analysis/executable, including `Onyx.exe` and `Onyx-GoogleWorkspace.exe`. No
   clean, reset, checkout, stage, commit, push, PR, build or install is implied.
2. Source mode preserves the exact seven-dependency aggregate and every v1.2.6
   functional/security invariant, not the old full-closure identity. It defines
   and records a new successor member list, exact count and root, continuously
   authenticates that successor, and receives fresh independent review.
   Existing focused/adversarial/combined 1.0-1.2 tests pass without relaxed
   assertions, skipped security cases or replacement fakes.
3. Frozen mode is selected only by exact built-in `sys.frozen is True`, uses a
   distinct versioned productive manifest, and cannot load or accept the source
   seven-file manifest as its runtime authority.
4. The raw frozen manifest exactly follows the closed typed schema, NFC/case/
   path rules, canonical JSON separators/order and leaf/root algorithm defined
   above. A compiled authority pins its raw digest before interpretation. The
   manifest binds the productive closure and boot/predecessor hashes but contains
   no later build-input, bundle, artifact, installed, release or signature root.
   Non-empty module names are unique; empty module values may repeat only for
   data/entrypoint members. Every `entrypoints`/`predecessors` digest cross-binds
   to exactly one required canonical entry path with the same digest.
   The acyclic graph is manifest <- build-input seal <- per-Analysis bundle
   inventory <- release manifest <- signature. Every malformed, drifted,
   colliding, linked/reparse or traversing input fails before side effects.
5. The frozen productive manifest and staged GWS additions contain no **new GWS**
   tests, stories, source-only provenance manifest/CLI dependency, `build_*`
   script, cache, log, credential, owner data or development evidence. The exact
   three historical sealed V24/HUD test inputs in
   `RUNTIME_TEST_EVIDENCE_FILES` remain unchanged. No new GWS compatibility
   exception is added.
6. `scripts/package_hygiene.py` stages exactly the GWS bootstrap, launcher,
   packaged helper, frozen manifest and manifest-declared productive closure,
   including required productive `actions`, `memory` and Python `dashboard`
   modules. Source tree breadth is not used as the frozen closure definition.
7. `packaging/onyx.spec` contains explicit GWS hidden imports/data and a
   Windows-only `Onyx-GoogleWorkspace.exe` target. Static tests prove
   `google.genai` is not misclassified as GWS and each logical productive member
   occurs once per PyInstaller Analysis/executable. Any physical duplication
   across separate one-file executables is explicitly represented in their
   separate inventories and is not misreported as one shared bundle copy.
8. With no case-insensitive occurrence of either GWS flag, stable bootstrap
   selection reaches the exact current V24 path without opening, hashing or
   importing GWS files and with zero GWS config/vault/audit/directory/thread/
   browser/network/provider side effects.
9. Any case-insensitive occurrence of either GWS flag causes the stable bootstrap
   to stable-read and hash-authenticate the exact GWS bootstrap before executing
   its captured bytes and before POSIX selection. Only the exact canonical pair
   with exact built-in string value `true` enables the branch. Preload/path/link/
   hash drift plus the exhaustive absent, partial, alias, casing, whitespace,
   alternate-value and conflict matrix otherwise fail closed and redacted.
10. V24 activation/bootstrap/launcher bytes and default declaration set remain
    unchanged. Default-off source tests compare the exact predecessor hashes and
    selected target; no test falsely asserts the modified stable bootstrap is
    byte-identical.
11. Source and frozen bootstraps authenticate the GWS launcher and activation
    before execution. Frozen activation authenticates the compiled raw-manifest
    digest authority, captures every verified productive source byte and installs
    one authoritative finder before GWS first-party execution. No preloaded or
    unmanifested first-party import or normal unsealed PYZ GWS import is accepted
    throughout construction, dispatch, helper handling, rollback and shutdown;
    continuous health fencing detects every drift.
12. The packaged helper has one CLI-first entrypoint with `configure`, `status`,
    `connect`, `disconnect`, bounded Gmail/Calendar tests and canonical launch.
    It enters the existing single controller/broker/service/audit lifecycle and
    never calls consequential host methods directly. Consequential commands
    require a fresh trusted broker decision bound to exact helper/owner/command/
    arguments/nonce/trace/expiry; CLI/model/process text cannot approve. No
    duplicate credential store, tool, broker or controller exists.
13. A dedicated packaged provider-free diagnostic emits the versioned JSON
    contract, runtime-measured manifest/closure/predecessor values and the
    defined native-vault-derived stable pseudonym. Harness-supplied later roots
    appear only under `untrusted_external_inputs` with their untrusted label.
    Tests prove zero DNS/socket/HTTP/browser/provider calls and never fabricate
    missing identity.
14. Every startup/install-stage failure point is source-tested for transactional
    rollback, retained cleanup authority, one-shot predecessor rollback and the
    existing three bounded launcher cleanup attempts. No residual GWS
    declaration, service, worker, listener, lease, audit handle or provenance
    authority remains after successful cleanup. Frozen logs/rendezvous exist
    only in owner-data with restrictive permissions and never under `_MEIPASS`,
    install or source roots.
15. `scripts/build_release.py` source changes remove every GWS flag key,
    case-insensitive alias and GWS configuration field from baseline smoke
    environments, and define later frozen default-off, malformed/partial and
    enabled/status provider-free smoke inputs and candidate-bound evidence
    validation. The helper launch path authenticates `Onyx.exe`, builds a
    sanitized allowlisted environment, uses argv plus `shell=False`, and requires
    an authenticated post-spawn receipt; ambiguous dispatch is `UnknownOutcome`.
    No build function is executed in this story.
16. `docs/INSTALLATION.md` describes GWS as Windows-only, default-off and not yet
    released; documents helper intent, read-only scopes, disconnect/revoke and
    the distinction between provider-free and provider acceptance without
    claiming installed availability.
17. Focused source tests cover selector, staging, hygiene, spec, manifest,
    helper, smoke, redaction, failure/rollback and source/frozen isolation.
    Combined 1.0/1.1/1.2 regressions, Ruff and `py_compile` pass. Applicable root
    quality gates are reported truthfully; absence of `Onyx/package.json` is not
    converted into a fake npm pass.
18. Independent Architecture and QA each issue source-only GO for the exact
    candidate bytes. Their verdict explicitly excludes Git/pre-PR, build,
    package artifact, installation, provider, deployment and release readiness.

## Tasks / Subtasks

- [ ] Resolve the implementation-entry blocker (AC: 1).
  - [ ] Record a read-only content-addressed isolated candidate containing all
    accepted 1.0-1.2 tracked and untracked inputs, per-file hashes and candidate
    root, or record explicit overwrite authority for each dirty surface and then
    create the same snapshot before edits.
  - [ ] Record the exact manifest path and raw digest for every Analysis/
    executable, including `Onyx.exe` and `Onyx-GoogleWorkspace.exe`.
  - [ ] Re-read the exact candidate bytes and confirm no unrelated work will be
    discarded, normalized or absorbed.
  - [ ] Record fresh PO/Architecture readiness after Draft 0.2; Draft 0.1
    verdicts remain NOT READY.
- [ ] Implement the source/frozen authority split (AC: 2-5, 11).
  - [ ] Preserve the seven-dependency aggregate and v1.2.6 functional/security
    invariants; generate and record a new successor-source member list, count
    and root for independent review.
  - [ ] Implement the exact closed typed schema, NFC/case/path rules, canonical
    separators/order and leaf/root algorithm in
    `core/google_workspace_packaged_provenance_v1.py`.
  - [ ] Enforce uniqueness only for non-empty module values and cross-bind every
    entrypoint/predecessor index to its exact canonical entry path/digest.
  - [ ] Generate a compiled raw-manifest digest authority, authenticate it
    before interpretation, and enforce manifest <- build-input <- per-Analysis
    bundle <- release <- signature without later roots inside the manifest.
  - [ ] Execute every GWS first-party lifecycle module from captured verified
    manifest bytes through one authoritative finder/health fence; reject
    preload, unmanifested import and normal unsealed PYZ fallback.
  - [ ] Add tamper, link/reparse, traversal, collision, extra/missing and mode-
    confusion tests.
- [ ] Integrate productive staging and PyInstaller declarations (AC: 5-7).
  - [ ] Add only GWS productive entrypoints and manifest-declared modules to
    staging.
  - [ ] Add required productive `actions`, `memory` and Python `dashboard`
    content without new GWS test/story/build trees while preserving exactly the
    three sealed historical V24/HUD test inputs.
  - [ ] Add explicit GWS hidden imports/data and Windows helper target to the
    spec.
  - [ ] Prove per-Analysis/executable uniqueness, explicit cross-executable
    physical duplication, hygiene, third-party inventory and license/SBOM
    behavior.
- [ ] Implement stable selection and authenticated branch entry (AC: 8-11).
  - [ ] Add case-insensitive flag-occurrence routing before POSIX selection.
  - [ ] Stable-read and hash-authenticate the GWS bootstrap locally before
    executing captured bytes.
  - [ ] Preserve exact both-absent V24 behavior and zero GWS access.
  - [ ] Exhaustively test canonical, partial, malformed, alias and conflict
    environments in source and simulated-frozen harnesses.
- [ ] Implement the packaged helper source contract (AC: 7, 12).
  - [ ] Enter the single controller/broker/service/audit lifecycle; add only a
    non-model helper adapter and prohibit raw-host consequential calls.
  - [ ] Require exact trusted approval proofs for configure/connect/disconnect/
    revoke/enable/launch; reject CLI, process and model-text approval claims.
  - [ ] Provide typed, redacted command results and canonical launch selection.
  - [ ] Authenticate `Onyx.exe`, construct an allowlisted sanitized environment,
    spawn with argv and `shell=False`, and verify an owner-data HMAC post-spawn
    receipt before success.
  - [ ] Fence real browser/network/provider activity in all story tests.
- [ ] Implement the provider-free diagnostic and release-source hooks (AC: 13,
  15).
  - [ ] Emit and validate the exact versioned redacted JSON contract.
  - [ ] Derive the stable host pseudonym from a dedicated native-vault key with
    the specified create/reuse/rotation lifecycle.
  - [ ] Separate runtime-measured roots from explicitly untrusted harness inputs.
  - [ ] Install measurable DNS/socket/HTTP/browser/provider fences before host
    construction.
  - [ ] Sanitize all GWS flags/config from baseline smoke environments.
  - [ ] Define later candidate-bound smoke inputs without executing any build.
- [ ] Preserve lifecycle and cleanup guarantees (AC: 14).
  - [ ] Inject failure before and after each frozen composition/publication
    stage.
  - [ ] Prove retained cleanup authority, primary-error preservation, bounded
    retries and no residual owned resources.
  - [ ] Prove all frozen logs/rendezvous use restrictive owner-data paths and
    never `_MEIPASS`, install or source roots.
- [ ] Update truthful operator documentation (AC: 16).
  - [ ] Document Windows-only/default-off/helper/scopes/revoke semantics.
  - [ ] Label build, installed lifecycle, provider and release as unavailable.
- [ ] Complete source-only verification (AC: 2-18).
  - [ ] Run focused and adversarial test matrix.
  - [ ] Run combined GWS 1.0/1.1/1.2 regressions.
  - [ ] Run Ruff, `py_compile` and applicable repository quality gates.
  - [ ] Update every task checkbox, Change Log, Dev Agent Record and File List.
  - [ ] Obtain independent Architecture and QA source-only verdicts.

## Test Matrix

| Layer | Required cases | Required result | Explicitly does not prove |
|---|---|---|---|
| Dirty-worktree entry gate | Eight dirty surfaces; ordinary Git worktree missing untracked baseline; incomplete/content-drifted snapshot | Only a complete content-addressed 1.0-1.2 candidate or explicit per-file overwrite plus snapshot resolves blocker | Candidate implementation correctness |
| Authority mode | Seven-dependency aggregate; old 704-module root; new successor count/root; simulated frozen; missing/forged `sys.frozen`; cross-mode manifest | Fixed seven dependencies and invariants preserved; new source successor independently identified; exact mode authority accepted | Real PyInstaller behavior |
| Frozen manifest | Raw compiled digest; per-Analysis path/digest binding; duplicate JSON keys; closed types; repeated empty versus non-empty modules; entrypoint/predecessor cross-binding; NFC/case/separators/order/root; byte/size/path drift; missing/extra; collisions; traversal; link/reparse; self-authentication; forbidden later roots | Raw hash before interpretation; exact schema/root/index binding; Analysis isolation; acyclic evidence; fail closed before GWS import/side effect | Signed artifact |
| Frozen imports | Preloaded module; normal PYZ fallback; unmanifested lazy import; finder precedence/code/path drift across dispatch/rollback/shutdown | Every GWS first-party module executes captured verified bytes and health fence remains authoritative | Third-party supply-chain acceptance |
| Stable selector | Both absent; canonical pair; each partial; wrong casing/value/type/whitespace; aliases/conflicts; Windows/POSIX ordering | Absent -> exact V24; canonical pair -> GWS; all ambiguity -> sanitized refusal | Installed shortcut/autostart |
| Staging/hygiene | Per-Analysis closure; required actions/memory/dashboard; new GWS tests/stories/build/cache/log/credential injections; three sealed historical V24/HUD test inputs; exception attempt | Logical member once per Analysis; allowed cross-executable physical copies inventoried; new development/sensitive payload rejected; historical predecessor preserved | Built bundle contents |
| PyInstaller spec | GWS hidden imports/data; compiled manifest-digest authority; helper target; platform guard; per-Analysis inventory; staged/spec parity; `google.genai` distinction | Static/source contract complete and deterministic | Successful PyInstaller build |
| Helper | Single controller/broker; trusted approvals; raw-host/model/CLI bypass; typed output; authenticated Onyx.exe; env sanitization; `shell=False`; post-spawn receipt; redaction | No duplicate authority or approval bypass; launch success is post-spawn verified; no secret/content leakage | Real configuration persistence/provider |
| Provider-free smoke | Runtime-measured roots; untrusted harness roots; native-vault pseudonym lifecycle; owner-data logs; network/browser/provider fences; receipt redaction | One schema-valid `provider-free` receipt, correct trust labels and zero external calls | Provider acceptance |
| Lifecycle | Fault at each construction/publication/cleanup stage; concurrent shutdown; three rollback failures; retry | Primary failure retained; owned resources cleaned exactly once or cleanup-pending retained | Process/OS crash recovery in installed app |
| Regression | Existing connector, host, live adapter, activation, permission/audit and operational suites | No relaxed/skipped security assertions | End-to-end installed readiness |
| Static quality | Ruff, `py_compile`, secret/PII/path scan, manifest reproducibility | All changed source/test files clean; roots reproduce | Gate B/Gate C |

All pytest runs must use a repository-local `--basetemp` on Windows. A fake,
monkeypatch, source harness, simulated `sys.frozen` or copied install fixture is
labelled as such and may not be reported as native frozen, installed or provider
evidence.

## Gate Model

### Implementation Entry — blocked

Blocked until a read-only content-addressed isolated candidate includes all
accepted tracked and untracked GWS 1.0-1.2 inputs with exact inventory/root, or
the owner explicitly authorizes overwrite of every named dirty surface and the
complete baseline is snapshotted before edits. A normal Git worktree and PO
validation alone do not resolve this authority/provenance blocker. Draft 0.2
also requires fresh PO and Architecture readiness verdicts.

### Gate A — source-only packaging integration

This story may close only after the exact candidate preserves the seven-
dependency aggregate and v1.2.6 functional invariants, records/reproduces its
new successor-source count/root, and passes the full matrix plus independent
Architecture and QA reviews. A Gate A GO means only that the frozen package
contract is internally consistent in source; it does not mean a package exists.

### Gate B — Git/pre-PR provenance prerequisite

Before PR, `@devops` must receive separate authorization to index the exact GWS
1.0/1.1/1.2/1.3 productive bytes, both provenance authorities and their
manifests together, then recompute roots and rerun the source gates from that
indexed baseline. This story authorizes no add, stage, commit, push or PR.

### Gate C — deferred

The following remain NO-GO and require later stories/evidence:

1. Windows candidate build and provider-free smoke across raw bundle, ZIP and
   isolated Setup (`ONYX-GWS-1.4`).
2. Installed helper/configuration lifecycle, persistent explicit selection,
   autostart/reboot, clean install, upgrade, uninstall, rollback and owner-data
   preservation (`ONYX-GWS-1.5`).
3. Owner-consented real Google OAuth/provider acceptance for connect, status,
   bounded Gmail/Calendar reads, restart and disconnect/revoke
   (`ONYX-GWS-1.6`).
4. Signed final-artifact repetition, clean-host evidence and formal release
   binding (`ONYX-GWS-1.7`).
5. Independent macOS/Linux host, vault, OAuth, package and provider acceptance.

Evidence never inherits between these gates.

## Dev Notes

### Previous Story Insights

- The v1.2.6 source branch preserves the seven-dependency aggregate but also
  authenticates a 704-module closure rooted at
  `2e79471dc9e8e3a27be114f89e98e02a95c72ff2bf90b560e6e3f5a154b1605b`.
  Because this story edits members of that closure, it must create and review a
  new successor count/root instead of claiming full cryptographic identity. The
  broad source closure still cannot be copied unchanged into production.  
  [Source: `docs/stories/ONYX-GWS-1.2.0.md#status`]
- Existing GWS policy, audit/idempotency, receipts, continuous provenance health
  and retryable lifecycle cleanup are mandatory reuse, not implementation
  options.  
  [Source: `docs/stories/ONYX-GWS-1.2.0.md#completion-notes-list`]
- The production host factory uses native authority with `provision=False`;
  packaging therefore needs a dedicated helper path for initial configuration
  instead of silently provisioning during normal live startup.  
  [Source: `core/google_workspace_host_v1.py` production factory]

### Current Package Findings

- Stable `scripts/bootstrap_onyx.pyw` currently selects V24 on Windows and has no
  GWS branch.  
  [Source: `scripts/bootstrap_onyx.pyw#_selected_bootstrap`]
- `scripts/package_hygiene.py` stages all top-level core modules and a narrow
  V8-V24 script list. It rejects new tests and `build_*` scripts while retaining
  exactly three historical sealed V24/HUD test inputs through
  `RUNTIME_TEST_EVIDENCE_FILES`.
  [Source: `scripts/package_hygiene.py#RUNTIME_SCRIPT_FILES`; Source:
  `scripts/package_hygiene.py#stage_runtime_sources`; Source:
  `scripts/package_hygiene.py#audit_package_tree`]
- `packaging/onyx.spec` collects `google.genai` for Gemini and has no GWS helper
  target. Its current `actions`, `memory` and `dashboard` declarations do not
  establish the on-disk frozen source closure expected by the source GWS
  activation.  
  [Source: `packaging/onyx.spec` package collection and hidden-import sections]
- The current GWS native startup smoke executes `status` but does not emit the
  required candidate-bound provider-free JSON contract.  
  [Source: `scripts/launch_onyx_live_google_workspace_v1.pyw#run`]
- The source activation scans the checkout under `actions`, `core`, `dashboard`,
  `memory` and `scripts`; this is a source integrity boundary, not a productive
  package inventory.  
  [Source:
  `core/onyx_live_activation_google_workspace_v1.py#_captured_local_closure`]

### Project Structure Notes

- All implementation remains inside the existing `Onyx/core`, `Onyx/scripts`,
  `Onyx/packaging`, `Onyx/tests` and `Onyx/docs` layout.
- CLI-first is preserved through `Onyx-GoogleWorkspace.exe`; no UI work is
  authorized.
- No new database or external API contract is introduced. Existing native vault
  and GWS host/connector boundaries remain authoritative.
- Current packaging sources are mixed/dirty, so file-path correctness does not
  grant overwrite authority.

### Testing Standards

- Follow the existing pytest patterns in
  `tests/test_google_workspace_live_v1.py`,
  `tests/test_onyx_live_activation_google_workspace_v1.py` and package/build
  contract tests.
- Use subprocess isolation for environment, stable-bootstrap and `sys.frozen`
  tests; do not trust mutable in-process module state as frozen evidence.
- Use repository-local `--basetemp` because the global Windows pytest temp root
  can deny access.
- Network, DNS, socket, browser and provider fences must be installed before the
  tested host boundary is constructed.
- Test receipts and exceptions for secrets, PII, content, raw paths and nested
  `__cause__`/`__context__` leakage.
- Root npm gates are applied only if applicable; Onyx currently has no local
  `package.json`, so Python-focused gates must be reported separately and
  truthfully.

## 🤖 CodeRabbit Integration

### Story Type Analysis

**Primary Type:** Deployment/Packaging  
**Secondary Types:** Architecture, Security, Integration  
**Complexity:** High — crosses the stable selector, authenticated runtime
closure, PyInstaller staging/spec, helper boundary, evidence and rollback while
preserving a source-approved security contract.

### Specialized Agent Assignment

**Primary Agents:**

- `@dev` — implementation and pre-commit review
- `@architect` — source/frozen trust chain and lifecycle quality gate

**Supporting Agents:**

- `@qa` — adversarial selector, hygiene, redaction and rollback verification
- `@devops` — Gate B/pre-PR and later candidate build only when separately
  authorized

### Quality Gate Tasks

- [ ] Pre-Commit (`@dev`): review exact uncommitted story candidate; verify
  package hygiene, provenance, secrets and backward compatibility.
- [ ] Pre-PR (`@devops`): blocked until separate Gate B authority and indexed
  provenance exist.
- [ ] Pre-Deployment (`@devops`): not part of this story; remains Gate C.

### Self-Healing Configuration

**Expected Self-Healing:**

- Primary Agent: `@dev` (light mode)
- Max Iterations: 2
- Timeout: 15 minutes
- Severity Filter: CRITICAL only

**Predicted Behavior:**

- CRITICAL issues: repair within this story's source-only scope and rerun all
  affected gates, at most two iterations.
- HIGH issues: document and return to Architecture/QA; do not widen scope.
- MEDIUM/LOW issues: record according to the reviewing gate.

### CodeRabbit Focus Areas

**Primary Focus:**

- Source/frozen mode confusion, self-authenticating manifests and pre-import
  trust-chain gaps.
- Development or sensitive payload leakage through staging, spec or helper.
- Default-off drift, partial-flag bypass and platform-selector ordering.
- Secret/PII/content leakage in helper output, exceptions and smoke evidence.

**Secondary Focus:**

- Transactional publication, cleanup ownership and bounded rollback retries.
- Existing 1.2.6 policy, audit, idempotency and receipt compatibility.
- Deterministic manifest/staging/spec parity and candidate identity binding.
- False build/install/provider/release claims in code, tests or documentation.

## Story Draft Checklist

- [x] Problem, user value and relationship to 1.2.0 are explicit.
- [x] Goals and non-goals bound the story to source-only packaging integration.
- [x] Dirty/untracked file conflict and implementation-entry blocker are explicit.
- [x] Key file surfaces and authority boundaries are listed.
- [x] Source-versus-frozen provenance and trust chain are specified.
- [x] Dual-flag/default-off V24 selection is exact and testable.
- [x] Staging excludes new GWS tests/stories/build scripts and sensitive payload
  while preserving the three sealed historical V24/HUD test inputs.
- [x] Packaged-helper responsibilities and non-authorities are explicit.
- [x] Provider-free smoke schema, redaction and external-I/O fences are defined.
- [x] Security, lifecycle and rollback invariants are explicit.
- [x] Acceptance criteria are measurable and map to tasks/tests.
- [x] Gate B prerequisite and Gate C deferrals are explicit.
- [x] CodeRabbit assignment and source-only quality gates are populated.
- [x] Architecture approved exact helper/provenance module paths.
- [x] PO declared Draft 0.2 story definition READY and implementation NOT READY.
- [x] Architecture declared Draft 0.2 story readiness GO and implementation
  entry NO-GO.
- [ ] Architecture validates the exact content-addressed isolated candidate
  inventory, per-Analysis manifest paths/digests and successor root.
- [ ] Implementation-entry blocker is resolved.

**Draft validation:** `DEFINITION READY; BLOCKED FOR IMPLEMENTATION`.
The story is self-contained for a competent Dev once the dirty-surface authority
blocker is resolved and the exact candidate baseline receives independent
Architecture validation.

## Change Log

| Date | Version | Description | Author |
|---|---:|---|---|
| 2026-08-10 | 0.1.0 | Initial frozen-provenance and source-only package-integration story derived from GWS v1.2.6 Gate A and the read-only Gate C architecture/package audit | Chronos (`@sm`) |
| 2026-08-10 | 0.1.1 | PO Draft 0.1 **NOT READY**: required exact `Draft` token, standalone continuation trace, explicit dirty-surface authority and isolated baseline | Themis (`@po`) |
| 2026-08-10 | 0.1.2 | Architecture Draft 0.1 **NOT READY**: required successor root, acyclic provenance, compiled pin, captured-byte execution, predecessor-test preservation and single-controller helper authority | Vega (`@architect`) |
| 2026-08-10 | 0.2.0 | Incorporated all blocking Draft 0.1 PO/Architecture findings; exact module/helper paths accepted; content-addressed candidate remained blocked | Chronos (`@sm`) |
| 2026-08-10 | 0.2.1 | PO Draft 0.2: **READY story definition / NOT READY implementation**; completeness 9.6/10, actionability 9.4/10, testability 9.7/10 | Themis (`@po`) |
| 2026-08-10 | 0.2.2 | Architecture Draft 0.2: **GO story readiness / NO-GO implementation entry** pending exact content-addressed candidate and baseline validation | Vega (`@architect`) |
| 2026-08-10 | 0.2.3 | Added nonblocking module-uniqueness and per-Analysis manifest-path/index cross-binding clarifications; preserved Draft/blocker and Gate B/C deferrals | Chronos (`@sm`) |

## Dev Agent Record

### Agent Model Used

Not started.

### Debug Log References

Not started. No build, package, installation, provider or Git action is
authorized.

### Completion Notes List

- Implementation is blocked pending an isolated candidate or explicit overwrite
  authority plus a content-addressed baseline for the dirty/untracked surfaces
  listed in Blocked.

### File List

- `docs/stories/ONYX-GWS-1.3.0.md` (new story; only file created during story
  preparation)
- Implementation file list: pending Dev; must be updated before review.

## QA Results

**Pending.** QA must independently validate the exact isolated source candidate,
test results, redaction, staging hygiene, default-off equivalence, rollback and
the absence of build/install/provider claims. QA cannot promote a simulated
frozen harness to Gate C evidence.

## Architecture Review Results

**Draft 0.1: NOT READY / NO-GO to start implementation.** Architecture verified
the exact dirty surfaces, the fixed seven-dependency aggregate, the old
704-module/root closure and the installed V23-only boundary. It found the old
full-closure identity incompatible with required edits, a circular provenance
graph, no binding between staged `.py` hashes and normal PYZ execution, an
overbroad test exclusion that would break three sealed V24/HUD inputs, and an
undefined helper approval authority. It additionally required the closed
canonical schema, compiled raw-manifest digest, authenticated stable-bootstrap
handoff, lifecycle-wide manifested imports, per-Analysis uniqueness,
authenticated/sanitized/post-verified launch, native-vault pseudonym lifecycle,
untrusted harness-root labels, owner-data-only logs and a content-addressed
baseline containing untracked 1.0-1.2 inputs.

Architecture accepted the exact paths
`core/google_workspace_packaged_provenance_v1.py` and
`scripts/onyx_google_workspace_packaged_v1.py`.

**Draft 0.2: GO for story readiness / NO-GO for implementation entry.** All
blocking architectural definition findings are closed. Architecture requested
two nonblocking clarifications, now incorporated: module uniqueness applies only
to non-empty module values, and the candidate record names exact manifest paths
per Analysis while cross-binding entrypoint/predecessor indexes to entries.
Implementation remains blocked pending the exact content-addressed candidate,
its inventory/root/per-Analysis manifests and independent baseline validation.
No overwrite, build, installation, provider use, Git or release is authorized.

## PO Validation

**Draft 0.1: NOT READY.** PO scored the draft 9.2/10 for completeness but required
the exact `**Draft**` status token, a separate blocker, standalone continuation
trace, exact dirty-surface inventory, isolated baseline or per-file overwrite
authority, Architecture path/baseline approval, and recorded review/changelog.

Those documentation findings are incorporated in Draft 0.2. The filesystem and
content-addressed candidate blocker remains open.

**Draft 0.2: READY for story definition / NOT READY for implementation.** PO
confirmed all 18 acceptance criteria, tasks/test coverage, exact executor/gate
separation and Gate A/B/C evidence boundaries. Scores: completeness 9.6/10,
actionability after unblock 9.4/10 and testability 9.7/10. Implementation remains
blocked until the exact candidate inventory/root is recorded and independently
validated; this PO verdict grants no overwrite, Git, build, installation,
provider or release authority.
