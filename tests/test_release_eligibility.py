import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from scripts import check_release_eligibility as eligibility
from scripts.check_release_eligibility import check_release_eligibility
from scripts.generate_release_sbom import INVENTORY_COMMENT_PREFIX, write_sbom
from core.native_activation_contract_v1 import activation_contract_for_system_v1


class ReleaseEligibilityTests(unittest.TestCase):
    VERSION = "1.2.3"
    WORKFLOW_RUN_ID = "119"
    WORKFLOW_SHA = "c" * 40

    @staticmethod
    def _signed_pe() -> bytes:
        data = bytearray(512)
        data[:2] = b"MZ"
        data[0x3C:0x40] = (0x80).to_bytes(4, "little")
        data[0x80:0x84] = b"PE\0\0"
        data[0x98:0x9A] = (0x10B).to_bytes(2, "little")
        directory = 0x98 + 96 + (8 * 4)
        data[directory:directory + 4] = (480).to_bytes(4, "little")
        data[directory + 4:directory + 8] = (32).to_bytes(4, "little")
        data[480:512] = b"AUTHENTICODE-EVIDENCE".ljust(32, b"\0")
        return bytes(data)

    def _valid_fixture(self, root: Path) -> Path:
        (root / "LICENSE").write_text(
            "Onyx Product License\nCopyright Cyryx Labs. Distribution requires "
            "the permissions stated in this license.\n",
            encoding="utf-8",
        )
        (root / "THIRD_PARTY_NOTICES.md").write_text(
            "# Third-Party Notices\nCopyright and license notices for every "
            "distributed dependency are recorded in this reviewed document.\n",
            encoding="utf-8",
        )
        release = root / "release"
        release.mkdir()
        (root / "requirements.lock").write_text(
            "demo-dependency==4.5.6 \\\n"
            "    --hash=sha256:" + "a" * 64 + "\n",
            encoding="utf-8",
        )
        artifact = release / f"Onyx-{self.VERSION}-Windows-test64-Portable.zip"
        with zipfile.ZipFile(artifact, "w") as archive:
            info = zipfile.ZipInfo("Onyx/Onyx.exe", (2026, 1, 1, 0, 0, 0))
            archive.writestr(info, self._signed_pe())
        artifact_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
        setup = release / f"Onyx-{self.VERSION}-Windows-test64-Setup.exe"
        setup.write_bytes(self._signed_pe())
        setup_hash = hashlib.sha256(setup.read_bytes()).hexdigest()
        bundle_inventory = {
            "contract": "OnyxBundleInventory.v1",
            "product": "Onyx",
            "version": self.VERSION,
            "system": "Windows",
            "architecture": "test64",
            "bundleRootSha256": "b" * 64,
            "fileCount": 1,
            "symlinkCount": 0,
            "files": [],
            "symlinks": [],
            "runtimeDistributionCount": 1,
            "runtimeDistributionRootSha256": "c" * 64,
            "runtimeDistributions": [
                {
                    "name": "demo-dependency",
                    "normalizedName": "demo-dependency",
                    "version": "4.5.6",
                    "licenseDeclared": "MIT",
                    "metadataPath": "_internal/demo_dependency-4.5.6.dist-info/METADATA",
                    "metadataSha256": "d" * 64,
                    "legalFiles": [],
                }
            ],
        }
        bundle_path = release / "bundle-inventory-Windows-test64.json"
        bundle_path.write_text(
            json.dumps(bundle_inventory, sort_keys=True), encoding="utf-8"
        )
        bundle_hash = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
        seal = release / ("pyinstaller-first-party-inputs-" + "e" * 64 + ".json")
        seal.write_text('{"contract":"test-seal"}\n', encoding="utf-8")
        seal_hash = hashlib.sha256(seal.read_bytes()).hexdigest()
        subject = "CN=Cyryx Labs LLC"
        thumbprint = "A" * 40
        signature = {
            "name": "Onyx.exe",
            "size": len(self._signed_pe()),
            "sha256": hashlib.sha256(self._signed_pe()).hexdigest(),
            "authenticode_status": "Valid",
            "signer_subject": subject,
            "signer_thumbprint": thumbprint,
            "timestamp_subject": "CN=Trusted Timestamp Authority",
            "timestamp_thumbprint": "B" * 40,
        }
        setup_signature = {
            **signature,
            "name": setup.name,
            "sha256": setup_hash,
        }
        evidence = release / "windows-release-evidence-test64.json"
        evidence.write_text(
            json.dumps(
                {
                    "contract": "onyx.windows-release-evidence.v1",
                    "version": self.VERSION,
                    "architecture": "test64",
                    "formal": True,
                    "trust_provider": "Windows Authenticode",
                    "verification_policy": (
                        "signtool /pa /all /v and Get-AuthenticodeSignature Valid"
                    ),
                    "signer_subject": subject,
                    "signer_thumbprint": thumbprint,
                    "timestamp_url": "https://timestamp.example.invalid",
                    "all_trusted": True,
                    "bundle_pe_files": [{**signature, "path": "Onyx.exe"}],
                    "signed_installers": [setup_signature],
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        evidence_hash = hashlib.sha256(evidence.read_bytes()).hexdigest()
        manifest = {
            "product": "Onyx",
            "publisher": "Cyryx Labs",
            "version": self.VERSION,
            "system": "Windows",
            "release_class": "formal",
            "diagnostic_exceptions": [],
            "release_trust": {
                "contract": "onyx.release-trust.v1",
                "formal_requested": True,
                "platform": "Windows",
                "signing_policy": "authenticode-trusted",
            },
            "build_input_seal": {
                "contract": "OnyxPyInstallerFirstPartyInputs.v1",
                "file_count": 1,
                "root_sha256": "e" * 64,
                "manifest": seal.name,
                "manifest_sha256": seal_hash,
                "manifest_size": seal.stat().st_size,
            },
            "activation_contract": activation_contract_for_system_v1("Windows"),
            "architecture": "test64",
            "bundle_inventory": {
                "name": bundle_path.name,
                "size": bundle_path.stat().st_size,
                "sha256": bundle_hash,
                "contract": "OnyxBundleInventory.v1",
                "bundle_root_sha256": "b" * 64,
                "file_count": 1,
                "runtime_distribution_count": 1,
                "runtime_distribution_root_sha256": "c" * 64,
            },
            "artifacts": [
                {
                    "name": artifact.name,
                    "size": artifact.stat().st_size,
                    "sha256": artifact_hash,
                },
                {
                    "name": setup.name,
                    "size": setup.stat().st_size,
                    "sha256": setup_hash,
                },
                {
                    "name": evidence.name,
                    "size": evidence.stat().st_size,
                    "sha256": evidence_hash,
                },
            ],
        }
        (release / "release-manifest-Windows-test64.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        checksum_records = [
            *(f"{item['sha256']}  {item['name']}\n" for item in manifest["artifacts"]),
            f"{seal_hash}  {seal.name}\n",
            f"{bundle_hash}  {bundle_path.name}\n",
        ]
        (release / "SHA256SUMS-Windows-test64.txt").write_text(
            "".join(checksum_records), encoding="utf-8"
        )
        write_sbom(
            root=root,
            release_dir=release,
            version=self.VERSION,
            created="2026-07-14T00:00:00Z",
        )
        return release

    @staticmethod
    def _rewrite_sbom(release: Path, sbom: dict) -> None:
        path = release / "SBOM.spdx.json"
        path.write_text(
            json.dumps(sbom, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        (release / "SBOM.spdx.json.sha256").write_text(
            f"{digest}  SBOM.spdx.json\n", encoding="utf-8"
        )

    @staticmethod
    def _inventory(sbom: dict) -> dict:
        return json.loads(sbom["comment"].removeprefix(
            INVENTORY_COMMENT_PREFIX
        ))

    @staticmethod
    def _replace_inventory(sbom: dict, inventory: dict) -> None:
        sbom["comment"] = INVENTORY_COMMENT_PREFIX + json.dumps(
            inventory, sort_keys=True, separators=(",", ":")
        )

    def _native_receipt(
        self,
        release: Path,
        *,
        ci_bound: bool = False,
    ) -> dict[str, object]:
        manifest_path = release / "release-manifest-Windows-test64.json"
        setup = release / f"Onyx-{self.VERSION}-Windows-test64-Setup.exe"
        portable = release / f"Onyx-{self.VERSION}-Windows-test64-Portable.zip"
        evidence = json.loads(
            (release / "windows-release-evidence-test64.json").read_text(
                encoding="utf-8"
            )
        )
        setup_signature = dict(evidence["signed_installers"][0])
        setup_signature["path"] = setup.name
        bundle_signature = dict(evidence["bundle_pe_files"][0])
        bundle_signature["path"] = "Onyx/Onyx.exe"
        return {
                "contract": "onyx.windows-native-eligibility-receipt.v1",
                "decision": "eligible",
                "version": self.VERSION,
                "architecture": "test64",
                "workflow_run_id": self.WORKFLOW_RUN_ID if ci_bound else "",
                "workflow_run_attempt": "1" if ci_bound else "",
                "workflow_sha": self.WORKFLOW_SHA if ci_bound else "",
                "manifest": {
                    "name": manifest_path.name,
                    "size": manifest_path.stat().st_size,
                    "sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                },
                "setup": {
                    "name": setup.name,
                    "size": setup.stat().st_size,
                    "sha256": hashlib.sha256(setup.read_bytes()).hexdigest(),
                },
                "portable": {
                    "name": portable.name,
                    "size": portable.stat().st_size,
                    "sha256": hashlib.sha256(portable.read_bytes()).hexdigest(),
                },
                "signer_subject": evidence["signer_subject"],
                "signer_thumbprint": evidence["signer_thumbprint"],
                "verified_pe_files": [setup_signature, bundle_signature],
        }

    def _persist_ci_native_receipt(self, release: Path) -> str:
        receipt_path = release / "windows-native-eligibility-receipt-test64.json"
        receipt_path.write_text(
            json.dumps(self._native_receipt(release, ci_bound=True)),
            encoding="utf-8",
        )
        return hashlib.sha256(receipt_path.read_bytes()).hexdigest()

    def _check(
        self, root: Path, release: Path, approval: str = "true",
        legal_approval: str = "true",
    ):
        def native_verifier(**_: object) -> dict[str, object]:
            return self._native_receipt(release)

        if os.name == "nt":
            return check_release_eligibility(
                root=root,
                release_dir=release,
                version=self.VERSION,
                repository_approval=approval,
                legal_approval=legal_approval,
                windows_native_verifier=native_verifier,
            )

        trusted_receipt_sha256 = ""
        manifest_path = release / "release-manifest-Windows-test64.json"
        if manifest_path.is_file():
            trusted_receipt_sha256 = self._persist_ci_native_receipt(release)
        with mock.patch.dict("os.environ", {"GITHUB_ACTIONS": "true"}):
            return check_release_eligibility(
                root=root,
                release_dir=release,
                version=self.VERSION,
                repository_approval=approval,
                legal_approval=legal_approval,
                windows_native_verifier=native_verifier,
                trusted_windows_receipt_sha256=trusted_receipt_sha256,
                workflow_run_id=self.WORKFLOW_RUN_ID,
                workflow_sha=self.WORKFLOW_SHA,
            )

    def test_ci_receipt_hash_and_workflow_identity_are_exactly_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = self._valid_fixture(root)
            manifest = json.loads(
                (release / "release-manifest-Windows-test64.json").read_text(
                    encoding="utf-8"
                )
            )
            receipt = self._native_receipt(release, ci_bound=True)
            receipt_path = release / "windows-native-eligibility-receipt-test64.json"
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            local_errors: list[str] = []
            with mock.patch.dict("os.environ", {}, clear=True):
                eligibility._validate_windows_native_receipt(
                    release_dir=release,
                    manifest=manifest,
                    receipt=None,
                    trusted_receipt_sha256=hashlib.sha256(
                        receipt_path.read_bytes()
                    ).hexdigest(),
                    require_ci_binding=True,
                    workflow_run_id=self.WORKFLOW_RUN_ID,
                    workflow_sha=self.WORKFLOW_SHA,
                    errors=local_errors,
                )
            self.assertIn(
                "WINDOWS_NATIVE_VERIFICATION_REQUIRED: a local attestation cannot authorize formal Windows eligibility",
                local_errors,
            )
            errors: list[str] = []
            with mock.patch.dict("os.environ", {"GITHUB_ACTIONS": "true"}):
                eligibility._validate_windows_native_receipt(
                    release_dir=release,
                    manifest=manifest,
                    receipt=None,
                    trusted_receipt_sha256="0" * 64,
                    require_ci_binding=True,
                    workflow_run_id=self.WORKFLOW_RUN_ID,
                    workflow_sha=self.WORKFLOW_SHA,
                    errors=errors,
                )
            self.assertIn(
                "WINDOWS_NATIVE_RECEIPT_DRIFT: Windows job receipt hash does not match downloaded bytes",
                errors,
            )

    def test_valid_approval_legal_files_sbom_and_release_manifest_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = self._valid_fixture(root)
            self.assertEqual(self._check(root, release), ())

    @unittest.skipIf(os.name == "nt", "cross-host receipt authority is POSIX-only")
    def test_non_windows_ignores_injected_verifier_and_uses_ci_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = self._valid_fixture(root)
            trusted_receipt_sha256 = self._persist_ci_native_receipt(release)
            injected = mock.Mock(side_effect=AssertionError("must not be called"))

            with mock.patch.dict("os.environ", {"GITHUB_ACTIONS": "true"}):
                errors = check_release_eligibility(
                    root=root,
                    release_dir=release,
                    version=self.VERSION,
                    repository_approval="true",
                    legal_approval="true",
                    windows_native_verifier=injected,
                    trusted_windows_receipt_sha256=trusted_receipt_sha256,
                    workflow_run_id=self.WORKFLOW_RUN_ID,
                    workflow_sha=self.WORKFLOW_SHA,
                )

            self.assertEqual(errors, ())
            injected.assert_not_called()

    def test_repository_approval_must_be_explicitly_true(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = self._valid_fixture(root)
            errors = self._check(root, release, approval="false")
            self.assertIn(
                "repository approval variable ONYX_PUBLIC_RELEASE_APPROVED is not true",
                errors,
            )

    def test_legal_approval_must_be_explicitly_true(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = self._valid_fixture(root)
            errors = self._check(root, release, legal_approval="false")
            self.assertIn(
                "legal approval variable ONYX_LEGAL_RELEASE_APPROVED is not true",
                errors,
            )

    def test_missing_legal_and_release_evidence_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            errors = self._check(root, root / "release", approval="")
            self.assertTrue(any(error.startswith("missing product license") for error in errors))
            self.assertTrue(any(error.startswith("missing third-party notices") for error in errors))
            self.assertTrue(any(error.startswith("missing SPDX SBOM") for error in errors))
            self.assertTrue(any(error.startswith("missing release directory") for error in errors))

    def test_placeholder_legal_text_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = self._valid_fixture(root)
            (root / "LICENSE").write_text(
                "LICENSE PLACEHOLDER TODO: insert the approved license before release.",
                encoding="utf-8",
            )
            errors = self._check(root, release)
            self.assertIn("invalid product license: unresolved placeholder marker", errors)

    def test_sbom_must_match_version_and_its_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = self._valid_fixture(root)
            sbom_path = release / "SBOM.spdx.json"
            sbom = json.loads(sbom_path.read_text(encoding="utf-8"))
            sbom["packages"][0]["versionInfo"] = "0.0.0"
            sbom_path.write_text(json.dumps(sbom), encoding="utf-8")
            errors = self._check(root, release)
            self.assertIn(
                f"invalid SPDX SBOM: no Onyx package matches release version {self.VERSION}",
                errors,
            )
            self.assertIn("invalid SBOM digest manifest: SBOM SHA-256 mismatch", errors)

    def test_release_manifest_hash_detects_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = self._valid_fixture(root)
            artifact = release / f"Onyx-{self.VERSION}-Windows-test64-Portable.zip"
            artifact.write_bytes(b"tampered package bytes")
            errors = self._check(root, release)
            self.assertTrue(
                any(
                    error.startswith(f"invalid release artifact {artifact.name}:")
                    for error in errors
                )
            )

    def test_release_manifest_activation_contract_is_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = self._valid_fixture(root)
            manifest_path = release / "release-manifest-Windows-test64.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["activation_contract"] = activation_contract_for_system_v1(
                "Linux"
            )
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            errors = self._check(root, release)

            self.assertIn(
                "invalid release manifest release-manifest-Windows-test64.json: "
                "activation contract is absent or mismatched",
                errors,
            )

    def test_release_class_and_zero_diagnostic_exceptions_are_mandatory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = self._valid_fixture(root)
            manifest_path = release / "release-manifest-Windows-test64.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest.pop("release_class")
            manifest["diagnostic_exceptions"] = ["forged-local-exception"]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            errors = self._check(root, release)

            self.assertIn(
                "invalid release manifest release-manifest-Windows-test64.json: "
                "release_class must be formal",
                errors,
            )
            self.assertIn(
                "invalid release manifest release-manifest-Windows-test64.json: "
                "diagnostic exceptions must be empty",
                errors,
            )

    def test_forged_valid_fields_cannot_hide_unsigned_windows_pe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = self._valid_fixture(root)
            setup = release / f"Onyx-{self.VERSION}-Windows-test64-Setup.exe"
            unsigned = bytearray(self._signed_pe())
            directory = 0x98 + 96 + (8 * 4)
            unsigned[directory:directory + 8] = b"\0" * 8
            setup.write_bytes(unsigned)
            evidence_path = release / "windows-release-evidence-test64.json"
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            installer = evidence["signed_installers"][0]
            installer["size"] = setup.stat().st_size
            installer["sha256"] = hashlib.sha256(setup.read_bytes()).hexdigest()
            installer["authenticode_status"] = "Valid"
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
            manifest_path = release / "release-manifest-Windows-test64.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for record in manifest["artifacts"]:
                path = release / record["name"]
                record["size"] = path.stat().st_size
                record["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            write_sbom(
                root=root,
                release_dir=release,
                version=self.VERSION,
                created="2026-07-14T00:00:00Z",
            )

            errors = self._check(root, release)

            self.assertIn(
                "invalid Windows installer evidence: PE Authenticode certificate table is absent",
                errors,
            )

    def test_required_target_matrix_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = self._valid_fixture(root)
            errors = check_release_eligibility(
                root=root,
                release_dir=release,
                version=self.VERSION,
                repository_approval="true",
                legal_approval="true",
                required_targets=("Windows-test64", "Linux-x64"),
            )
            self.assertIn("missing required release targets: Linux-x64", errors)

    def test_sbom_requires_exact_locked_package_coverage_without_license_claims(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = self._valid_fixture(root)
            sbom_path = release / "SBOM.spdx.json"
            sbom = json.loads(sbom_path.read_text(encoding="utf-8"))
            dependency = next(
                item for item in sbom["packages"] if item["name"] == "demo-dependency"
            )
            self.assertEqual(dependency["licenseConcluded"], "NOASSERTION")
            self.assertEqual(dependency["licenseDeclared"], "NOASSERTION")
            sbom["packages"].remove(dependency)
            self._rewrite_sbom(release, sbom)

            errors = self._check(root, release)

            self.assertIn(
                "invalid SPDX SBOM: package records do not exactly cover the lock",
                errors,
            )

    def test_sbom_requires_every_archive_member_and_its_exact_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = self._valid_fixture(root)
            sbom_path = release / "SBOM.spdx.json"
            sbom = json.loads(sbom_path.read_text(encoding="utf-8"))
            inventory = self._inventory(sbom)
            artifact = inventory["artifacts"][0]
            member = artifact["members"].pop()
            sbom["files"] = [
                item for item in sbom["files"] if item["SPDXID"] != member["spdxId"]
            ]
            sbom["relationships"] = [
                item
                for item in sbom["relationships"]
                if item["relatedSpdxElement"] != member["spdxId"]
            ]
            self._replace_inventory(sbom, inventory)
            self._rewrite_sbom(release, sbom)

            errors = self._check(root, release)

            self.assertIn(
                f"invalid SPDX SBOM: member file coverage mismatch for "
                f"Onyx-{self.VERSION}-Windows-test64-Portable.zip",
                errors,
            )

    def test_sbom_outer_artifact_hash_is_bound_to_release_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = self._valid_fixture(root)
            sbom_path = release / "SBOM.spdx.json"
            sbom = json.loads(sbom_path.read_text(encoding="utf-8"))
            inventory = self._inventory(sbom)
            artifact = inventory["artifacts"][0]
            artifact["sha256"] = "0" * 64
            self._replace_inventory(sbom, inventory)
            self._rewrite_sbom(release, sbom)

            errors = self._check(root, release)

            self.assertIn(
                f"invalid SPDX SBOM: artifact inventory mismatch for "
                f"Onyx-{self.VERSION}-Windows-test64-Portable.zip: sha256",
                errors,
            )

    def test_sbom_fails_closed_when_dependency_lock_changes_after_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = self._valid_fixture(root)
            (root / "requirements.lock").write_text(
                "other-dependency==7.8.9 \\\n"
                "    --hash=sha256:" + "b" * 64 + "\n",
                encoding="utf-8",
            )

            errors = self._check(root, release)

            self.assertIn(
                "invalid SPDX SBOM: dependency lock SHA-256 mismatch", errors
            )
            self.assertIn(
                "invalid SPDX SBOM: dependency lock package coverage mismatch",
                errors,
            )

    def test_sbom_generation_is_byte_deterministic_for_identical_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            release = self._valid_fixture(root)
            first = (release / "SBOM.spdx.json").read_bytes()
            parsed = json.loads(first)
            self.assertNotIn("onyxReleaseInventory", parsed)
            self.assertTrue(parsed["comment"].startswith(INVENTORY_COMMENT_PREFIX))
            write_sbom(
                root=root,
                release_dir=release,
                version=self.VERSION,
                created="2026-07-14T00:00:00Z",
            )
            second = (release / "SBOM.spdx.json").read_bytes()
            self.assertEqual(first, second)

    def test_generator_cli_resolves_inputs_from_unrelated_working_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "fixture"
            root.mkdir()
            release = self._valid_fixture(root)
            (release / "SBOM.spdx.json").unlink()
            (release / "SBOM.spdx.json.sha256").unlink()
            unrelated = Path(tmp) / "unrelated"
            unrelated.mkdir()
            project = Path(__file__).resolve().parents[1]
            script = project / "scripts" / "generate_release_sbom.py"

            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--root",
                    str(root),
                    "--release-dir",
                    "release",
                    "--version",
                    self.VERSION,
                    "--source-date-epoch",
                    "1782864000",
                ],
                cwd=unrelated,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertIn("Release SBOM generation: PASS", result.stdout)
            self.assertEqual(self._check(root, release), ())

    def test_workflow_package_command_never_crashes_on_core_import(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "scripts.check_release_eligibility",
                "--version",
                "1.0.0",
                "--repository-approval",
                "true",
                "--legal-approval",
                "true",
            ],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

        self.assertIn(result.returncode, {0, 1})
        self.assertIn("Public release eligibility:", result.stdout)
        self.assertNotIn("ModuleNotFoundError", result.stderr)
        self.assertNotIn("No module named 'core'", result.stderr)

    def test_package_command_resolves_core_from_project_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture_root = Path(tmp) / "fixture"
            fixture_root.mkdir()
            release = self._valid_fixture(fixture_root)
            project = Path(__file__).resolve().parents[1]

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scripts.check_release_eligibility",
                    "--root",
                    str(fixture_root),
                    "--release-dir",
                    str(release),
                    "--version",
                    self.VERSION,
                    "--repository-approval",
                    "true",
                    "--legal-approval",
                    "true",
                ],
                cwd=project,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )

            self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
            self.assertIn("Public release eligibility: BLOCKED", result.stdout)
            self.assertIn("WINDOWS_NATIVE_VERIFICATION", result.stdout)
            self.assertNotIn("ModuleNotFoundError", result.stderr)

    def test_direct_script_command_resolves_core_from_any_working_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture_root = Path(tmp) / "fixture"
            fixture_root.mkdir()
            release = self._valid_fixture(fixture_root)
            project = Path(__file__).resolve().parents[1]

            result = subprocess.run(
                [
                    sys.executable,
                    str(project / "scripts/check_release_eligibility.py"),
                    "--root",
                    str(fixture_root),
                    "--release-dir",
                    str(release),
                    "--version",
                    self.VERSION,
                    "--repository-approval",
                    "true",
                    "--legal-approval",
                    "true",
                ],
                cwd=fixture_root,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )

            self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
            self.assertIn("Public release eligibility: BLOCKED", result.stdout)
            self.assertIn("WINDOWS_NATIVE_VERIFICATION", result.stdout)
            self.assertNotIn("ModuleNotFoundError", result.stderr)

    def test_publication_workflow_generates_inventory_before_eligibility(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/release-packages.yml").read_text(
            encoding="utf-8"
        )
        generator = workflow.index("python scripts/generate_release_sbom.py")
        eligibility = workflow.index("python -m scripts.check_release_eligibility")
        self.assertLess(generator, eligibility)
        self.assertIn("--source-date-epoch", workflow)


if __name__ == "__main__":
    unittest.main()
