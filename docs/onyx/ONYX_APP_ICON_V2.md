# Onyx application icon V2

Date: 2026-07-23  
Status: active product icon

## Decision

The Onyx desktop/application icon contains only the neural Orb. The square
canvas surrounding the Orb is transparent. No black tile, outer arc, corner
square, text or third-party identity is part of the icon.

Master:

`packaging/assets/onyx-app-icon-master-v2.png`

SHA-256:

`38851712eded8a1529ca116dff56b77d5a6df436e142014fa9dbdbad361a14fe`

The master is an RGBA square image. Its four corner regions are fully
transparent, its center is opaque and the visible alpha bounding box retains
safe padding for Windows, macOS and Linux icon masks.

## Generated resources

`scripts/generate_icons.py` derives:

- `build/assets/onyx.png`
- `build/assets/onyx.ico`
- `build/assets/onyx.icns`
- `build/assets/version_info.txt`

The same `.ico` is copied to `config/onyx.ico` for source-checkout shortcuts.
Windows process and shortcut identity remain `labs.cyryx.onyx`.

## Source

The V2 cutout was produced using the built-in image edit workflow with the V1
Orb as the edit target, a flat magenta chroma source, and the installed
background-removal helper. The chroma source is not a runtime asset.
