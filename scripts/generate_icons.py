"""Generate official Cyryx Labs Onyx application icons."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
MASTER_ICON = ROOT / "packaging" / "assets" / "onyx-app-icon-master-v2.png"
WINDOWS_ICON_SIZES = (
    (16, 16),
    (24, 24),
    (32, 32),
    (48, 48),
    (64, 64),
    (128, 128),
    (256, 256),
)


def render_icon(
    size: int = 1024,
    *,
    source: Path = MASTER_ICON,
) -> Image.Image:
    """Load the official Orb master and normalize it for platform encoders."""
    if size < 16:
        raise ValueError("icon size must be at least 16 pixels")
    if not source.is_file():
        raise FileNotFoundError(f"official Onyx icon master is missing: {source}")
    with Image.open(source) as opened:
        if opened.width != opened.height:
            raise ValueError("official Onyx icon master must be square")
        if min(opened.size) < 1024:
            raise ValueError("official Onyx icon master must be at least 1024x1024")
        image = opened.convert("RGBA")
    if image.size != (size, size):
        image = image.resize((size, size), Image.Resampling.LANCZOS)
    return image


def _version_tuple(version: str) -> tuple[int, int, int, int]:
    values = []
    for part in version.split(".")[:4]:
        digits = "".join(ch for ch in part if ch.isdigit())
        values.append(int(digits or 0))
    return tuple((values + [0, 0, 0, 0])[:4])


def write_version_info(path: Path, version: str) -> None:
    numbers = _version_tuple(version)
    path.write_text(
        f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={numbers}, prodvers={numbers}, mask=0x3f,
    flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('CompanyName', 'Cyryx Labs'),
    StringStruct('FileDescription', 'Onyx AI Assistant'),
    StringStruct('FileVersion', '{version}'),
    StringStruct('InternalName', 'Onyx'),
    StringStruct('LegalCopyright', 'Copyright Cyryx Labs'),
    StringStruct('OriginalFilename', 'Onyx.exe'),
    StringStruct('ProductName', 'Onyx'),
    StringStruct('ProductVersion', '{version}')
  ])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])]
)\n""",
        encoding="utf-8",
    )


def generate(output: Path, version: str, *, source: Path = MASTER_ICON) -> None:
    output.mkdir(parents=True, exist_ok=True)
    icon = render_icon(source=source)
    icon.save(output / "onyx.png", format="PNG")
    icon.save(
        output / "onyx.ico",
        format="ICO",
        sizes=WINDOWS_ICON_SIZES,
        # Pillow otherwise stores the larger ICO frames as embedded PNGs.
        # Windows accepts both encodings, but PyInstaller's CopyIcons resource
        # rewrite combined with PNG-backed frames has triggered false-positive
        # malware classification.  Classic DIB/BMP frames preserve the exact
        # Orb pixels and alpha channel while avoiding that byte pattern.
        bitmap_format="bmp",
    )
    icon.save(output / "onyx.icns", format="ICNS")
    write_version_info(output / "version_info.txt", version)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--version",
        required=True,
        help="authoritative release version; no implicit or stale default is allowed",
    )
    parser.add_argument("--source", type=Path, default=MASTER_ICON)
    args = parser.parse_args()
    generate(args.output.resolve(), args.version, source=args.source.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
