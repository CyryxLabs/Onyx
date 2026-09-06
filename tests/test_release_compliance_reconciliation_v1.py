import hashlib
import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.generate_release_sbom import write_sbom
from scripts.reconcile_release_compliance_v1 import (
    ComplianceReconciliationError,
    reconcile_release_compliance,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ReleaseComplianceReconciliationV1Tests(unittest.TestCase):
    VERSION = "1.2.3"

    def _fixture(self, root: Path) -> tuple[Path, Path]:
        release = root / "release"
        bundle = root / "bundle" / "Onyx"
        release.mkdir()
        bundle.mkdir(parents=True)
        source_files = {
            "LICENSE": "Cyryx Labs proprietary product license and permissions.\n",
            "THIRD_PARTY_NOTICES.md": "# Third-party copyright and license notices\n",
            "packaging/licenses/LGPL-3.0.txt": "GNU LESSER GENERAL PUBLIC LICENSE Version 3\n",
        }
        for relative, content in source_files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        (root / "requirements.lock").write_text(
            "demo-package==4.5.6 \\\n    --hash=sha256:" + "a" * 64 + "\n",
            encoding="utf-8",
        )

        bundle_payload = {
            "LICENSE.txt": source_files["LICENSE"],
            "THIRD_PARTY_NOTICES.md": source_files["THIRD_PARTY_NOTICES.md"],
            "THIRD_PARTY_LICENSES/LGPL-3.0.txt": source_files[
                "packaging/licenses/LGPL-3.0.txt"
            ],
            "_internal/demo_package-4.5.6.dist-info/METADATA": (
                "Name: demo-package\nVersion: 4.5.6\nLicense-Expression: MIT\n"
            ),
            "_internal/demo_package-4.5.6.dist-info/licenses/LICENSE": "MIT License\n",
            (
                "THIRD_PARTY_LICENSES/missing-distribution-evidence-v1/"
                "sample-1.0/NOTICE.txt"
            ): "sample notice\n",
            (
                "THIRD_PARTY_LICENSES/primp-1.3.1-native-crates/"
                "packages/sample-1.0/LICENSE"
            ): "sample crate license\n",
        }
        for relative, content in bundle_payload.items():
            path = bundle / Path(relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

        missing_notice = bundle / (
            "THIRD_PARTY_LICENSES/missing-distribution-evidence-v1/"
            "sample-1.0/NOTICE.txt"
        )
        missing_inventory = {
            "contract": "OnyxMissingDistributionLicenseBundle.v1",
            "legalDecision": "REQUIRED",
            "packages": [
                {
                    "name": "sample",
                    "version": "1.0",
                    "legalDecision": "REQUIRED",
                    "files": [
                        {"name": "NOTICE.txt", "sha256": _sha256(missing_notice)}
                    ],
                }
            ],
        }
        missing_path = bundle / (
            "THIRD_PARTY_LICENSES/missing-distribution-evidence-v1/inventory.json"
        )
        missing_path.write_text(
            json.dumps(missing_inventory, sort_keys=True), encoding="utf-8"
        )

        crate_license = bundle / (
            "THIRD_PARTY_LICENSES/primp-1.3.1-native-crates/"
            "packages/sample-1.0/LICENSE"
        )
        primp_inventory = {
            "contract": "OnyxPrimpNativeLicenseBundle.v1",
            "legalDecision": "REQUIRED",
            "packageCount": 1,
            "legalFileCount": 1,
            "packages": [
                {
                    "name": "sample",
                    "version": "1.0",
                    "legalFiles": [
                        {
                            "path": "packages/sample-1.0/LICENSE",
                            "size": crate_license.stat().st_size,
                            "sha256": _sha256(crate_license),
                        }
                    ],
                }
            ],
        }
        primp_path = bundle / (
            "THIRD_PARTY_LICENSES/primp-1.3.1-native-crates/inventory.json"
        )
        primp_path.write_text(
            json.dumps(primp_inventory, sort_keys=True), encoding="utf-8"
        )

        files = []
        for path in sorted(bundle.rglob("*"), key=lambda item: item.as_posix()):
            if path.is_file():
                files.append(
                    {
                        "path": path.relative_to(bundle).as_posix(),
                        "size": path.stat().st_size,
                        "sha256": _sha256(path),
                    }
                )
        metadata = bundle / "_internal/demo_package-4.5.6.dist-info/METADATA"
        license_file = bundle / (
            "_internal/demo_package-4.5.6.dist-info/licenses/LICENSE"
        )
        inventory = {
            "contract": "OnyxBundleInventory.v1",
            "product": "Onyx",
            "version": self.VERSION,
            "system": "Windows",
            "architecture": "test64",
            "bundleRootSha256": "b" * 64,
            "fileCount": len(files),
            "symlinkCount": 0,
            "files": files,
            "symlinks": [],
            "runtimeDistributionCount": 1,
            "runtimeDistributionRootSha256": "c" * 64,
            "runtimeDistributions": [
                {
                    "name": "demo-package",
                    "normalizedName": "demo-package",
                    "version": "4.5.6",
                    "licenseDeclared": "MIT",
                    "metadataPath": metadata.relative_to(bundle).as_posix(),
                    "metadataSha256": _sha256(metadata),
                    "legalFiles": [
                        {
                            "path": license_file.relative_to(bundle).as_posix(),
                            "size": license_file.stat().st_size,
                            "sha256": _sha256(license_file),
                        }
                    ],
                }
            ],
        }
        inventory_path = release / "bundle-inventory-Windows-test64.json"
        inventory_path.write_text(
            json.dumps(inventory, sort_keys=True), encoding="utf-8"
        )

        portable = release / f"Onyx-{self.VERSION}-Windows-test64-Portable.zip"
        with zipfile.ZipFile(portable, "w") as archive:
            for path in sorted(bundle.rglob("*"), key=lambda item: item.as_posix()):
                if path.is_file():
                    archive.write(path, "Onyx/" + path.relative_to(bundle).as_posix())
        setup = release / f"Onyx-{self.VERSION}-Windows-test64-Setup.exe"
        setup.write_bytes(b"MZ deterministic test setup")
        manifest = {
            "product": "Onyx",
            "version": self.VERSION,
            "system": "Windows",
            "architecture": "test64",
            "bundle_inventory": {
                "name": inventory_path.name,
                "size": inventory_path.stat().st_size,
                "sha256": _sha256(inventory_path),
                "contract": "OnyxBundleInventory.v1",
                "bundle_root_sha256": inventory["bundleRootSha256"],
                "file_count": inventory["fileCount"],
                "runtime_distribution_count": 1,
                "runtime_distribution_root_sha256": "c" * 64,
            },
            "artifacts": [
                {
                    "name": portable.name,
                    "size": portable.stat().st_size,
                    "sha256": _sha256(portable),
                },
                {
                    "name": setup.name,
                    "size": setup.stat().st_size,
                    "sha256": _sha256(setup),
                },
            ],
        }
        (release / "release-manifest-Windows-test64.json").write_text(
            json.dumps(manifest, sort_keys=True), encoding="utf-8"
        )
        write_sbom(
            root=root,
            release_dir=release,
            version=self.VERSION,
            created="2026-08-11T00:00:00Z",
        )
        return release, bundle

    def test_exact_candidate_and_installed_bytes_pass_without_legal_approval(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            release, bundle = self._fixture(root)
            installed = root / "installed"
            shutil.copytree(bundle, installed)
            receipt = reconcile_release_compliance(
                root=root,
                release_dir=release,
                version=self.VERSION,
                bundle_root=bundle,
                installed_root=installed,
            )

        self.assertEqual(receipt["status"], "passed")
        self.assertFalse(receipt["publicReleaseEligible"])
        self.assertFalse(receipt["legalApproval"]["granted"])
        self.assertEqual(receipt["bundle"]["fileCount"], 9)
        self.assertEqual(
            receipt["legalEvidence"]["runtimeDistributionsWithLegalFiles"], 1
        )

    def test_source_legal_payload_drift_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            release, bundle = self._fixture(root)
            (root / "LICENSE").write_text("drifted\n", encoding="utf-8")
            with self.assertRaisesRegex(
                ComplianceReconciliationError, "byte mismatch: LICENSE.txt"
            ):
                reconcile_release_compliance(
                    root=root,
                    release_dir=release,
                    version=self.VERSION,
                    bundle_root=bundle,
                )


if __name__ == "__main__":
    unittest.main()
