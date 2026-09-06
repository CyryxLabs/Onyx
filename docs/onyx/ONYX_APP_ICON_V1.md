# Onyx Official Application Icon V1

## Status

**SUPERSEDED** by `ONYX_APP_ICON_V2.md` on 2026-07-23.

This file preserves the immutable V1 design record and its original hash for
traceability only. It is not the current application-icon authority and must
not be used as a release-packaging input. The active icon is the transparent,
Orb-only V2 master documented in `ONYX_APP_ICON_V2.md`.

## Master

- Source: `packaging/assets/onyx-app-icon-master-v1.png`
- SHA-256: `4e227bfdb6d5ad38e963fb59db1995d4cbb52cae7ca72f54d1a01586bdc71303`
- Form: a single centered cognitive particle Orb on an Onyx/Obsidian field.
- Palette: Cyryx Labs Onyx, Obsidian, Graphite, Gunmetal, Steel, Silver,
  Core Teal and Teal Glow.

The mark contains no wordmark, letters, external arcs, orbit lines, HUD frame,
corner ornaments or third-party branding.

## Generated platform assets

`scripts/generate_icons.py` uses the immutable visual master and emits:

- `onyx.ico`: Windows multi-resolution application and shortcut icon.
- `onyx.icns`: macOS application bundle icon.
- `onyx.png`: Linux desktop, AppImage and package icon.

The release builder regenerates these files before PyInstaller packaging. The
desktop UI resolves the same master in a source checkout and the packaged PNG
inside frozen builds, so the window, executable and desktop shortcut share one
identity.

## Generation prompt

The built-in image generation path used the accepted Onyx particle Orb as a
visual reference. It requested a centered cinematic cognitive entity with
obsidian depth, a silver particle shell and sparse teal activation nodes,
constrained to the official Cyryx Labs palette. It explicitly excluded
external arcs, orbit lines, corner squares, frames, borders, text, letters,
robot or brain symbols, excessive neon and third-party fictional identities.
