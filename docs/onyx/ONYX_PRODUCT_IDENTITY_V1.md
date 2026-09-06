# Onyx product identity V1

Date: 2026-07-23

Status: active normative product-identity baseline. Current release readiness
and unresolved gates remain authoritative only in `CURRENT_RELEASE_STATUS.md`.

## Active identity

- Product name: **Onyx**
- Company: **Cyryx Labs**
- Windows product/executable: `Onyx.exe`
- Windows taskbar identity: `labs.cyryx.onyx`
- macOS bundle: `Onyx.app`
- macOS bundle identifier: `labs.cyryx.onyx`
- Linux desktop identity and icon key: `Onyx` / `onyx`
- Primary local workspace entry: `C:\MAAX_Assistant\Onyx`

No active runtime, packaging, installer, README or second-AI handoff surface
uses the previous product name.

## Official application icon

Master:

`packaging/assets/onyx-app-icon-master-v2.png`

SHA-256:

`38851712eded8a1529ca116dff56b77d5a6df436e142014fa9dbdbad361a14fe`

Generated platform resources:

- `build/assets/onyx.ico`
- `build/assets/onyx.icns`
- `build/assets/onyx.png`

The Windows installer and executable, macOS app bundle, Linux desktop entry,
Qt application/window and desktop shortcut all resolve these official
resources.

The V2 master contains only the Orb. Its surrounding canvas is transparent;
there is no black square, frame or opaque corner background.

Source-checkout launches declare `labs.cyryx.onyx` through
`SetCurrentProcessExplicitAppUserModelID` before Qt creates the application.
The desktop shortcut stores the same `System.AppUserModel.ID`, preventing
Windows from grouping the window under the Python host icon.

## Local path migration

Windows denied renaming the physical working directory while the active Codex
session held a workspace handle. To avoid interrupting implementation,
`C:\MAAX_Assistant\Onyx` is the active primary entry and currently resolves to
the existing working directory through an NTFS junction. Desktop startup and
the running V13 command line use only the Onyx path.

After the current Codex workspace is closed, the final physical migration is:

1. stop Onyx;
2. remove only the verified `C:\MAAX_Assistant\Onyx` junction;
3. rename the existing repository directory to `C:\MAAX_Assistant\Onyx`;
4. recreate/verify the Onyx shortcut;
5. reopen the workspace from the Onyx path.

Do not perform step 2 or 3 while the current Codex workspace is open. Do not
delete, copy over or reset the dirty repository as a substitute for the atomic
rename.

Historical immutable acceptance records may contain old absolute evidence
paths. They are provenance, not active product identity, and must not be edited
because their hashes are part of accepted evidence envelopes.

## Verification

```powershell
python -m pytest -q `
  tests\test_onyx_product_identity_v1.py `
  tests\test_onyx_app_icon_v1.py `
  tests\test_desktop_shortcut.py `
  tests\test_packaging_paths.py `
  --basetemp .pytest-onyx-product-identity-v1 `
  -o cache_dir=.pytest-onyx-product-identity-v1-cache
```

Recorded result: **19 passed**, zero failures/errors.

The live V13 window was reopened after shortcut regeneration and visually
verified with the official Orb in the native title bar. The shortcut property
store returned `labs.cyryx.onyx`.
