from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEGACY_PRODUCT = re.compile(r"mark(?:[- _]?xlviii|[- _]?48)", re.IGNORECASE)
ACTIVE_PRODUCT_FILES = (
    "readme.md",
    "main.py",
    "ui.py",
    "scripts/build_release.py",
    "scripts/generate_icons.py",
    "scripts/launch_onyx.pyw",
    "packaging/onyx.spec",
    "packaging/windows/onyx.iss",
    "packaging/linux/onyx.desktop",
    "scripts/bootstrap_onyx.pyw",
    "scripts/launch_onyx.cmd",
)


class OnyxProductIdentityV1Tests(unittest.TestCase):
    def test_active_product_surfaces_have_no_legacy_product_name(self) -> None:
        for relative in ACTIVE_PRODUCT_FILES:
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIsNone(
                LEGACY_PRODUCT.search(source),
                msg=f"legacy product identity found in {relative}",
            )

    def test_cross_platform_packages_use_onyx_identity_and_icon(self) -> None:
        windows = (ROOT / "packaging/windows/onyx.iss").read_text(encoding="utf-8")
        macos = (ROOT / "packaging/onyx.spec").read_text(encoding="utf-8")
        linux = (ROOT / "packaging/linux/onyx.desktop").read_text(encoding="utf-8")

        self.assertIn("AppName=Onyx", windows)
        self.assertIn("SetupIconFile={#SetupIcon}", windows)
        self.assertIn('name="Onyx.app"', macos)
        self.assertIn('bundle_identifier="labs.cyryx.onyx"', macos)
        self.assertIn("icon=str(icon)", macos)
        self.assertIn("Name=Onyx", linux)
        self.assertIn("Icon=onyx", linux)

    def test_primary_workspace_uses_stable_onyx_bootstrap(self) -> None:
        bootstrap = (ROOT / "scripts/bootstrap_onyx.pyw").read_text(encoding="utf-8")
        launcher = (ROOT / "scripts/launch_onyx.cmd").read_text(encoding="utf-8")
        self.assertIn("bootstrap_onyx_live_v19.pyw", bootstrap)
        self.assertNotIn("bootstrap_onyx_live_v13.pyw", bootstrap)
        self.assertIn("scripts\\bootstrap_onyx.pyw", launcher)


if __name__ == "__main__":
    unittest.main()
