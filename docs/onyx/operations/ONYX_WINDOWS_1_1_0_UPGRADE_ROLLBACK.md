# Onyx 1.1.0 Windows upgrade and rollback

> **VERSION-BOUND 1.1.0 RUNBOOK — NOT CURRENT RELEASE STATUS.** Preserve these
> historical invariants, but use the current candidate lifecycle procedure and
> [`CURRENT_RELEASE_STATUS.md`](../CURRENT_RELEASE_STATUS.md) for release claims.

Status: operator runbook for the 1.1.0 release candidate. It does not record a
completed build or installation.

## Invariants

- Keep Onyx stopped throughout backup, install diagnostics and rollback.
- Never delete or export Windows Credential Manager entries. The installer and
  this procedure do not change them.
- Preserve `%LOCALAPPDATA%\Cyryx Labs\Onyx` before the first 1.1.0 launch. It
  contains owner configuration, memory, audit and mission state and is outside
  the program directory.
- The installer may replace only application-owned files under
  `%LOCALAPPDATA%\Programs\Cyryx Labs\Onyx`.
- The Desktop and Start Menu shortcuts must target the installed `Onyx.exe`
  with empty arguments. A `.venv`, source checkout or versioned V13 bootstrap
  target is a failed upgrade.

## Pre-build rollback preservation

`scripts/build_release.py` archives every existing direct file in `release/`
before clearing that directory. The accepted 1.0.0/V19.1 set is stored under
`rollback/releases/onyx-1.0.0-v19.1/` with `archive-manifest.json`. A pre-existing
archive is reused only when every name, size and SHA-256 matches; different
bytes fail closed and are never overwritten.

Independently copy the stopped owner-data directory to a timestamped location
outside both the install and data directories. Use a copy, not a move, before
installation. Check the copy command exit status and retain the snapshot until
1.1.0 acceptance is complete.

## Source and package gates

The requested build version must exactly equal `core.version.__version__`.
Every PyInstaller first-party input is sealed into a content-addressed JSON
manifest. The release manifest records its root SHA-256, manifest SHA-256,
file count and content-addressed filename.

The production Setup keeps the canonical Cyryx Labs AppId. Setup install smoke
uses a separately compiled installer whose AppId is a deterministic UUID
derived from its temporary test context. It cannot update the production
uninstall registry entry.

## Post-install shortcut gate

After the canonical installer finishes and before using a Desktop shortcut:

```powershell
& 'C:\MAAX_Assistant\Onyx\.venv\Scripts\python.exe' `
  'C:\MAAX_Assistant\Onyx\scripts\verify_windows_release_shortcuts.py' `
  --install-root "$env:LOCALAPPDATA\Programs\Cyryx Labs\Onyx" `
  --repair-desktop
```

`--repair-desktop` replaces a stale source/V13 Desktop link. The verifier does
not rewrite the Start Menu link; that link must already have been produced by
the installer and must pass the same target, argument and working-directory
contract.

## Rollback

1. Stop Onyx and verify that no installed or source Onyx process remains.
2. Move the failed 1.1.0 data directory to a timestamped quarantine path; do
   not delete it or merge it into the prior snapshot.
3. Restore the complete pre-upgrade owner-data copy at
   `%LOCALAPPDATA%\Cyryx Labs\Onyx`.
4. Reinstall the archived 1.0.0 Setup only after its SHA-256 matches
   `8d3222d352c5dd3d78790c9dff4b2e0f93728b81b3ba3db56d232456a1724cd3`.
5. Confirm the restored `Onyx.exe` SHA-256 is
   `2749e96e881514f55a849982a1760c844953f10869f106d3d264a36b8406335d`.
6. Run package/preflight/native-startup diagnostics and validate both shortcuts
   before opening the restored UI.
7. Retain the quarantined 1.1.0 state for diagnosis until rollback acceptance
   is recorded.

Rollback is not complete merely because the old window opens. Version, hashes,
startup diagnostics, shortcut targets and restored owner identity must all be
verified.
