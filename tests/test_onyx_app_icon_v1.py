from __future__ import annotations

import hashlib
import shutil
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from scripts.generate_icons import (
    MASTER_ICON,
    WINDOWS_ICON_SIZES,
    generate,
    main,
    render_icon,
)

ROOT = Path(__file__).resolve().parents[1]
MASTER_SHA256 = "38851712eded8a1529ca116dff56b77d5a6df436e142014fa9dbdbad361a14fe"


class OfficialOnyxAppIconV1Tests(unittest.TestCase):
    @staticmethod
    def _ico_frames(path: Path) -> tuple[tuple[int, int, bytes], ...]:
        raw = path.read_bytes()
        reserved, kind, count = struct.unpack_from("<HHH", raw)
        if (reserved, kind) != (0, 1):
            raise AssertionError("not a canonical Windows ICO")
        frames = []
        for index in range(count):
            offset = 6 + index * 16
            width, height, _, _, _, _, size, payload_offset = struct.unpack_from(
                "<BBBBHHII", raw, offset
            )
            payload = raw[payload_offset : payload_offset + size]
            frames.append((width or 256, height or 256, payload))
        return tuple(frames)

    def test_master_is_hash_bound_square_and_high_resolution(self) -> None:
        self.assertTrue(MASTER_ICON.is_file())
        self.assertEqual(
            hashlib.sha256(MASTER_ICON.read_bytes()).hexdigest(),
            MASTER_SHA256,
        )
        with Image.open(MASTER_ICON) as image:
            self.assertEqual(image.width, image.height)
            self.assertGreaterEqual(image.width, 1024)

    def test_master_is_orb_only_with_transparent_corners_and_safe_area(self) -> None:
        with Image.open(MASTER_ICON) as opened:
            image = opened.convert("RGBA")
        edge = max(32, image.width // 12)
        corners = (
            (0, 0, edge, edge),
            (image.width - edge, 0, image.width, edge),
            (0, image.height - edge, edge, image.height),
            (
                image.width - edge,
                image.height - edge,
                image.width,
                image.height,
            ),
        )
        for box in corners:
            alpha = image.crop(box).getchannel("A")
            self.assertEqual(alpha.getextrema(), (0, 0))

        alpha = image.getchannel("A")
        left, top, right, bottom = alpha.getbbox() or (0, 0, 0, 0)
        minimum_margin = image.width * 0.10
        self.assertGreater(left, minimum_margin)
        self.assertGreater(top, minimum_margin)
        self.assertLess(right, image.width - minimum_margin)
        self.assertLess(bottom, image.height - minimum_margin)
        self.assertEqual(image.getpixel((image.width // 2, image.height // 2))[3], 255)

        histogram = alpha.histogram()
        visible = image.width * image.height - histogram[0]
        coverage = visible / (image.width * image.height)
        self.assertGreater(coverage, 0.35)
        self.assertLess(coverage, 0.50)

    def test_renderer_normalizes_master_without_procedural_redesign(self) -> None:
        rendered = render_icon(256)
        self.assertEqual(rendered.mode, "RGBA")
        self.assertEqual(rendered.size, (256, 256))
        self.assertEqual(rendered.getpixel((0, 0))[3], 0)
        with self.assertRaises(ValueError):
            render_icon(15)

    def test_cross_platform_outputs_are_complete(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            generate(output, "1.2.3")
            expected = {
                "onyx.png",
                "onyx.ico",
                "onyx.icns",
                "version_info.txt",
            }
            self.assertEqual({path.name for path in output.iterdir()}, expected)

            with Image.open(output / "onyx.png") as png:
                self.assertEqual(png.size, (1024, 1024))
                self.assertEqual(png.mode, "RGBA")
            with Image.open(output / "onyx.ico") as ico:
                self.assertEqual(
                    set(ico.ico.sizes()),
                    set(WINDOWS_ICON_SIZES),
                )
            frames = self._ico_frames(output / "onyx.ico")
            self.assertEqual(
                {(width, height) for width, height, _ in frames},
                set(WINDOWS_ICON_SIZES),
            )
            self.assertTrue(all(payload.startswith(b"\x28\x00\x00\x00") for _, _, payload in frames))
            self.assertTrue(all(not payload.startswith(b"\x89PNG\r\n\x1a\n") for _, _, payload in frames))
            with Image.open(output / "onyx.icns") as icns:
                self.assertEqual(icns.size, (1024, 1024))

    def test_generated_assets_are_byte_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first"
            second = root / "second"
            generate(first, "1.2.3")
            generate(second, "1.2.3")

            self.assertEqual(
                {
                    path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in first.iterdir()
                },
                {
                    path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in second.iterdir()
                },
            )

    def test_icon_cli_requires_an_explicit_authoritative_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(
                sys,
                "argv",
                ["generate_icons.py", "--output", temporary],
            ):
                with self.assertRaises(SystemExit) as raised:
                    main()
        self.assertEqual(raised.exception.code, 2)

    @unittest.skipUnless(sys.platform == "win32", "PE resource probe is Windows-only")
    def test_pyinstaller_copyicons_and_version_info_leave_a_parseable_pe(self) -> None:
        import pefile
        from PyInstaller import config
        from PyInstaller.building import api as pyinstaller_api
        from PyInstaller.utils.win32 import icon, versioninfo

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            assets = root / "assets"
            generate(assets, "1.2.3")
            executable = root / "Onyx-probe.exe"
            bootloader = (
                Path(pyinstaller_api.HOMEPATH)
                / "PyInstaller"
                / "bootloader"
                / pyinstaller_api.PLATFORM
                / "runw.exe"
            )
            self.assertTrue(bootloader.is_file())
            shutil.copyfile(bootloader, executable)

            workpath = root / "pyinstaller-work"
            workpath.mkdir()
            with patch.dict(config.CONF, {"workpath": str(workpath)}):
                icon.CopyIcons(str(executable), str(assets / "onyx.ico"))
            info = versioninfo.load_version_info_from_text_file(
                assets / "version_info.txt"
            )
            versioninfo.write_version_info_to_executable(str(executable), info)

            pe = pefile.PE(str(executable), fast_load=False)
            try:
                resource_types = {
                    entry.id for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries
                }
                self.assertTrue(executable.read_bytes().startswith(b"MZ"))
                self.assertIn(pefile.RESOURCE_TYPE["RT_ICON"], resource_types)
                self.assertIn(pefile.RESOURCE_TYPE["RT_GROUP_ICON"], resource_types)
                self.assertIn(pefile.RESOURCE_TYPE["RT_VERSION"], resource_types)
            finally:
                pe.close()

    def test_runtime_and_packaging_resolve_the_official_master(self) -> None:
        ui_source = (ROOT / "ui.py").read_text(encoding="utf-8")
        build_source = (ROOT / "scripts" / "build_release.py").read_text(
            encoding="utf-8"
        )
        spec_source = (ROOT / "packaging" / "onyx.spec").read_text(encoding="utf-8")
        self.assertIn("onyx-app-icon-master-v2.png", ui_source)
        self.assertIn("setWindowIcon", ui_source)
        self.assertIn("SetCurrentProcessExplicitAppUserModelID", ui_source)
        self.assertIn('WINDOWS_APP_USER_MODEL_ID = "labs.cyryx.onyx"', ui_source)
        self.assertIn("PKEY_AppUserModel_ID", ui_source)
        self.assertIn("generate_assets(version)", build_source)
        for filename in ("onyx.png", "onyx.ico", "onyx.icns"):
            self.assertIn(filename, spec_source)


if __name__ == "__main__":
    unittest.main()
