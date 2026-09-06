# Frozen V9 launcher compatibility

`venvwlauncher-python313-x64.exe` was copied from
`Lib/venv/scripts/nt/venvwlauncher.exe` in the official CPython 3.13.7 AMD64
Windows installation. Its SHA-256 is fixed by the accepted Onyx V9, V10 and V11
runtime manifests:

`51361a2d68a5b4ecf1bad4d7214066e05f9598074e72662e62f7b2e3be3329b3`

It is packaged as immutable compatibility data only. Frozen Onyx executes
through its native PyInstaller entrypoint, not through this launcher. Keeping
the accepted bytes here makes clean Windows, macOS and Linux release checkouts
reproducible without relying on a developer-created repository `.venv`.

The launcher remains third-party CPython software, not Cyryx Labs proprietary
code. `PSF-LICENSE.txt` is the complete license notice shipped by that CPython
distribution and is copied beside the compatibility payload in every package.
