# Owner Profile V8 External E6 Acceptance

- Evidence ID: `VE-OWNER-PROFILE-V8-E6-001`
- Decision date: 2026-07-22
- Decision: **ACCEPTED - Owner Profile V8 only, frozen Windows candidate handoff**
- Candidate: `owner-profile-v8`

## Frozen candidate anchor

This independent record freezes the exact V8 candidate without changing any
candidate byte, restarting Onyx, creating a production credential, or adding a
live import.

| Anchor | SHA-256 |
|---|---|
| `core/owner_profile_v8.py` | `837295cfdf663dc97bf32592d186e0ba76ee74c83e1c757cfe420baea7dc0f3b` |
| `tests/test_owner_profile_v8.py` | `b835c5d213dd9bc1e58065c700e180046da2918b06da18c6539ff1916f6d2642` |
| `docs/onyx/checkpoints/owner-profile-v8/manifest.json` | `33f762cde3e23b00b0e89732b147b4aee28c68e6576fd38ba6c46c21c38b46c5` |

The candidate-manifest digest is the frozen root for this decision. It binds
the exact V8 implementation and tests, all V1-V7 historical core and test
bytes, the monotonic 63-bit sequence protocol, the lease-only journal
protocol, bounded compaction and the default-off/no-live-wiring boundary. Any
anchor drift invalidates this acceptance and requires a new version and new
independent gates.

## Independent gate decision

The independent functional, integrity and quality gates are **PASS** with
`P0=0, P1=0, P2=0, P3=0`.

| Gate | Reproduced evidence | Result |
|---|---|---|
| Functional | 17 focused tests; first contact, Unicode name, restart, correction, forget, 4096-to-4098 restart, long compaction, signed-63-bit terminal and no-write overflow refusal | PASS |
| Integrity | Exact V8 anchors and every V1-V7 core/test artifact rehashed; lease-only journal entry points, cached failure diagnostics, stale rollback and pre-forget resurrection defenses exercised | PASS |
| Quality | 201 cumulative tests plus 15 subtests; manifest's Ruff, format, bytecode and stable-reconcile evidence retained; no live V8 import found | PASS |

The exact independent reproductions on this Windows host completed as:

- focused V8: **17 passed, 0 failed** in 14.22 seconds;
- cumulative V1-V8 plus memory store: **201 passed, 15 subtests passed, 0 failed** in 109.12 seconds;
- real isolated Windows primitive gate: **PASS** for the actual Global named
  mutex and Credential Manager compare-and-set path from absent to genesis to
  terminal sequence 2, with exact readback and verified deletion of the unique
  temporary credential.

The pytest cache warning caused by the pre-existing inaccessible shared cache
did not affect collection, execution or the isolated `--basetemp` results.

## Preserved rejected history

V1 through V7 remain frozen historical/rejected candidates and are not
retroactively accepted. The V8 manifest records and the independent verifier
rehashes the following exact closure:

| Candidate | Core SHA-256 | Tests SHA-256 |
|---|---|---|
| V1 | `b2296227bb165f32117978e234519430af15838ad757104eeba08b8b7751b754` | `fafdf46a0a716f09aca81668ffda0b566af369be4d89095dc1be0a02209ee035` |
| V2 | `12c459c1d34376a121e7a837d6dbeca365967c69affdc12b7d3e18ea1c76cd73` | `76f0481f91b82b650ece00d86ad0bfffe21fa4020e46d8e3dcaaaf7e36832714` |
| V3 | `abf5e990b875a4ed04e9e9fed15eb550f972facf02b060683aa1e3abe88e4d16` | `f327a01f7d82a5df2d5e05d2bde70e3b89f06c6c4f69011e0ee257521033fe38` |
| V4 | `a3ab381ed50c6fd539b10775ce0058b51c5a06b89bd87b1156e6793f6f438fd5` | `ee57cc1f0b629f72cbdd8f7d53bc2fd78451a7524995c5eac74d6e60d043d5f0` |
| V5 | `53f6de7dfb7eb1f15f4f5c309257219a2ce67af7a662f0bb7e267fd1644daa18` | `1a4f9e2dcd5ec4ca1e3f4ff0390200ce56a6705dceb5499203d34a45dbab36ad` |
| V6 | `f5bc62f7c326acea61ff8e2508814cbbbd7ac2c4833b2bcccb5353d44c530e0d` | `72d44825c927704faae4f46802820babf89e4645d7cf16b33dc923289a155df1` |
| V7 | `6976ee481a9e494f4fa16548ac1d6a4eb8f5c160753cef3114b4d647220114e7` | `79f416d5d279b32e74279bcd981fbbe777b0f7886824e82149d6179b392d9466` |

V8 closes the V7 chain-head/cardinality coupling and post-lease diagnostic
read defects while preserving all previous positive behavior and the V7 disk
schema.

## Reproduction commands

Focused V8:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_owner_profile_v8.py --basetemp .pytest-owner-profile-v8-acceptance-focused
```

Cumulative V1-V8 and memory store:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_owner_profile_v1.py tests\test_owner_profile_v2.py tests\test_owner_profile_v3.py tests\test_owner_profile_v4.py tests\test_owner_profile_v5.py tests\test_owner_profile_v6.py tests\test_owner_profile_v7.py tests\test_owner_profile_v8.py tests\test_memory_store.py --basetemp .pytest-owner-profile-v8-acceptance-cumulative
```

Independent acceptance verifier, including a unique automatically cleaned
Windows primitive round-trip when run on Windows:

```powershell
.\.venv\Scripts\python.exe -I -S -B scripts\verify_owner_profile_v8_acceptance.py
```

The verifier must emit `OWNER_PROFILE_V8_ACCEPTANCE_OK`.

## Exact acceptance boundary

Accepted:

- the exact frozen V8 candidate root and V1-V7 historical closure;
- first-contact naming, Unicode normalization, correction, forget and restart
  behavior as exercised through the isolated owner authority;
- monotonic terminal sequencing through signed 63-bit maximum, bounded
  compaction independent of sequence, exact pair-capacity reservation and
  refusal before any write when the next terminal sequence cannot exist;
- lease-only journal, reconciliation, recovery, projection and chain-head CAS
  paths, including the real Windows Global mutex and Credential Manager
  primitives on the tested Windows host;
- an isolated/default-off implementation handoff for a separately reviewed
  live integration.

Not activated or accepted by this decision:

- imports, flags or replacement authority in `main.py`, `ui.py`, `dashboard/`,
  launchers or the running Onyx process;
- migration of an existing production owner profile or creation of a
  production Credential Manager record;
- macOS Keychain or Linux Secret Service chain-head/host-wide lease adapters;
- native macOS/Linux host validation, live wiring, installer activation,
  completion of a later PRD phase, or completion of Onyx as a whole.

V8 remains isolated, default-off and unwired. The candidate manifest's
candidate-time statement that external review was pending remains immutable
historical text; this separate record supplies that external acceptance for
the exact frozen root only.

## Platform boundary

The accepted platform evidence is Windows. macOS and Linux owner-profile
adapters and real-host gates remain explicit work outside this Windows
candidate. Atomic journal replacement also cannot prove physical-media flush
across every power-loss/filesystem combination. Neither limitation creates a
P0-P3 finding in this isolated Windows handoff, but both remain mandatory
considerations before cross-platform or live activation.
