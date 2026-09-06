# Onyx 1.1.8 runtime-delta record

Status: **pre-freeze comparison superseded; exact 1.1.8 qualification
pending**, updated 2026-08-03. This record does not replace final source,
artifact or test hashes.

## Compared baseline

The comparison source is the sealed Windows 1.1.7 first-party manifest:

- root SHA-256:
  `59edfeb39a98385b72416b2e7d4adfea949f0c8a431c018172af5343d3ac9a8b`
- manifest SHA-256:
  `25f968f1f73505260065333367db98805c55ed35e1e779613f65ad6217dced54`
- file count: 1,252

An early 1.1.8 comparison found only the following four differences:

| Path | Classification |
|---|---|
| `core/version.py` | Product version string only: 1.1.7 to 1.1.8 |
| `docs/onyx/CAPABILITY_MATRIX.md` | Documentation-precedence notice only |
| `packaging/onyx.spec` | Default build version only: 1.1.7 to 1.1.8 |
| `scripts/generate_icons.py` | Default generated version resource only: 1.1.7 to 1.1.8 |

That result is historical pre-freeze evidence only. It was superseded when
1.1.8 added the following release-enabling changes:

| Area | 1.1.8 change | Qualification consequence |
|---|---|---|
| `core/paths.py` | POSIX owner-controlled managed directories are repaired to mode `0700`; links and foreign ownership are rejected | Native POSIX path/startup and package tests are required |
| `core/native_startup_smoke_v1.py` | macOS/Linux startup prepares the managed data layout before descriptor-bound validation | Native startup evidence is required |
| `scripts/build_release.py` | Cross-platform package smoke uses the native interpreter outside the Windows-only harness condition | Per-platform build and package-smoke evidence is required |
| Linux release tooling | Container validation definition, exact AppImage tool pinning and associated tests/documentation | Native artifact and clean-host lifecycle evidence is still required |

These are bounded security and release-harness changes, but they are real code
changes. No current document may call the final 1.1.8 source byte-equivalent to
1.1.7. The final frozen input seal must enumerate every delta and establish
that unrelated engine, voice, authority and HUD paths did not change.

## Evidence use

The attempted 1.1.7 long-session soak ended early with an indeterminate process
exit and is not a pass. It cannot be transferred to 1.1.8. Exact frozen 1.1.8
artifacts must independently pass build, install/upgrade, startup, long-session,
uninstall/rollback, SBOM reconciliation and platform-signing gates.
