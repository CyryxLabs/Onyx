from __future__ import annotations

import tempfile
import unittest
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch
import shutil

from core import onyx_live_activation_v15 as v15
from core import onyx_live_activation_v9 as v9
from scripts.package_hygiene import (
    AEXOS_ATTESTED_MANIFEST_FILES,
    COMPATIBILITY_LAUNCHER_RELATIVE,
    COMPATIBILITY_LAUNCHER_SHA256,
    COMPATIBILITY_NOTICE_SHA256,
    COMPATIBILITY_EXCEPTIONS,
    CAPABILITY_RUNTIME_FILES,
    RUNTIME_HUD_ACCEPTANCE_MODULES,
    RUNTIME_HUD_ACCEPTANCE_MANIFESTS,
    RUNTIME_SCRIPT_FILES,
    RUNTIME_HUD_PREDECESSOR_INPUTS,
    RUNTIME_TEST_EVIDENCE_FILES,
    SOURCE_ONLY_HUD_AUTHORITY_FILES,
    STAGED_COMPATIBILITY_LAUNCHER,
    STAGED_COMPATIBILITY_NOTICE,
    assert_safe_build_input_paths,
    discover_runtime_docs,
    assert_embedded_chromium_runtime,
    package_hygiene_violations,
    prune_duplicate_browser_payloads,
    stage_runtime_docs,
    stage_runtime_sources,
)


ROOT = Path(__file__).resolve().parents[1]


def _exact_v15_test_environment(
    workspace_roots: tuple[Path, ...] | list[Path],
) -> dict[str, str]:
    """Build the legacy V15 contract without treating a Windows path as POSIX.

    V15 remains the Windows activation boundary.  These package-hygiene tests
    also run on Linux, where its default ``C:\\Program Files`` Docker CLI is
    neither absolute nor executable.  Bind the current native interpreter as
    an inert absolute path and declare the sandbox unavailable; the tests only
    validate activation/staging structure and never execute this placeholder.
    """

    options: dict[str, object] = {}
    if os.name != "nt":
        options.update(
            executable_docker_cli=str(Path(sys.executable).resolve()),
            executable_sandbox=False,
        )
    return v15.exact_activation_environment(workspace_roots, **options)


class PackageHygieneV1Tests(unittest.TestCase):
    def test_sensitive_machine_local_paths_are_rejected_without_content_scan(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            relative_paths = (
                "rollback/user-data-pre-1.1.8-20990101/config/api_keys.json",
                "onyx-bounded-diag-example/config/api_keys.json",
                "config/api_keys.json",
                "config/certs/onyx.key",
            )
            paths = []
            for relative in relative_paths:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
                paths.append(path)

            with patch.object(
                Path,
                "read_text",
                side_effect=AssertionError("sensitive content must not be read"),
            ):
                violations = package_hygiene_violations(root)

            self.assertEqual(len(violations), len(relative_paths))
            joined = "\n".join(violations)
            self.assertIn("machine-local user-data backup", joined)
            self.assertIn("machine-local diagnostic capture", joined)
            self.assertIn("credential store", joined)
            self.assertIn("private key", joined)
            for path in paths:
                with self.assertRaisesRegex(
                    Exception, "sensitive path entered build inputs"
                ):
                    assert_safe_build_input_paths((path,), root)

    def test_sensitive_worktree_patterns_are_narrowly_ignored(self) -> None:
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("/rollback/user-data-pre-*/", ignore)
        self.assertIn("/onyx*-diag-*/", ignore)

    def test_post_build_prunes_only_duplicate_shell_and_requires_full_chromium(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            browsers = root / "_internal/playwright/driver/package/.local-browsers"
            full = browsers / "chromium-1228"
            shell = browsers / "chromium_headless_shell-1228"
            executable_relative = (
                Path("chrome-win64/chrome.exe")
                if sys.platform == "win32"
                else (
                    Path("chrome-mac/Chromium.app/Contents/MacOS/Chromium")
                    if sys.platform == "darwin"
                    else Path("chrome-linux/chrome")
                )
            )
            (full / executable_relative).parent.mkdir(parents=True)
            (shell / "chrome-headless-shell-win64").mkdir(parents=True)
            (shell / "chrome-headless-shell-win64/shell.exe").write_bytes(b"duplicate")

            self.assertEqual(
                prune_duplicate_browser_payloads(root),
                (
                    "_internal/playwright/driver/package/.local-browsers/"
                    "chromium_headless_shell-1228",
                ),
            )
            self.assertFalse(shell.exists())
            with self.assertRaisesRegex(
                Exception, "full embedded Chromium executable is unavailable"
            ):
                assert_embedded_chromium_runtime(root)
            (full / executable_relative).write_bytes(b"full")
            self.assertTrue((full / executable_relative).is_file())
            assert_embedded_chromium_runtime(root)
            self.assertEqual(package_hygiene_violations(root), ())

            shutil.rmtree(full)
            with self.assertRaisesRegex(
                Exception, "full embedded Chromium runtime is unavailable"
            ):
                assert_embedded_chromium_runtime(root)

    def test_post_build_prune_refuses_matching_name_outside_playwright(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            imposter = root / "unrelated/chromium_headless_shell-1228"
            imposter.mkdir(parents=True)
            (imposter / "sentinel").write_bytes(b"keep")
            with self.assertRaisesRegex(Exception, "unsafe duplicate browser payload"):
                prune_duplicate_browser_payloads(root)
            self.assertEqual((imposter / "sentinel").read_bytes(), b"keep")

    def test_curated_staging_is_clean_and_keeps_only_bound_dev_named_inputs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            staging = Path(temporary)
            source_tree = staging / "runtime-sources"
            docs_tree = source_tree / "docs" / "onyx"
            stage_runtime_sources(ROOT, source_tree, allowed_build_root=staging)
            selected_docs = stage_runtime_docs(
                ROOT, docs_tree, allowed_build_root=staging
            )

            self.assertEqual(package_hygiene_violations(source_tree), ())
            self.assertEqual(
                {
                    path.relative_to(source_tree).as_posix()
                    for path in (source_tree / "tests").iterdir()
                },
                set(RUNTIME_TEST_EVIDENCE_FILES),
            )
            self.assertEqual(
                {
                    path.relative_to(source_tree).as_posix()
                    for path in (source_tree / "scripts").iterdir()
                },
                set(RUNTIME_SCRIPT_FILES)
                | {
                    relative
                    for relative in CAPABILITY_RUNTIME_FILES
                    if relative.startswith("scripts/")
                },
            )
            for relative in RUNTIME_HUD_ACCEPTANCE_MODULES:
                self.assertTrue((source_tree / relative).is_file(), relative)
            for relative in RUNTIME_HUD_ACCEPTANCE_MANIFESTS:
                self.assertTrue((source_tree / relative).is_file(), relative)
            staged_source_only = {
                relative
                for relative in SOURCE_ONLY_HUD_AUTHORITY_FILES
                if (source_tree / relative).exists()
            }
            self.assertEqual(staged_source_only, RUNTIME_HUD_PREDECESSOR_INPUTS)
            self.assertEqual(
                RUNTIME_HUD_PREDECESSOR_INPUTS,
                frozenset(
                    {
                        "docs/onyx/acceptance/"
                        "VE-HUD-CURRENT-V32-E6-001.manifest.json"
                    }
                ),
            )
            self.assertTrue(
                (source_tree / "scripts/bootstrap_onyx_live_v16.pyw").is_file()
            )
            self.assertTrue(
                (source_tree / "scripts/launch_onyx_live_v16.pyw").is_file()
            )
            self.assertTrue(
                (source_tree / "scripts/bootstrap_onyx_live_v17.pyw").is_file()
            )
            self.assertTrue(
                (source_tree / "scripts/launch_onyx_live_v17.pyw").is_file()
            )
            self.assertTrue(
                (source_tree / "scripts/bootstrap_onyx_live_v19.pyw").is_file()
            )
            self.assertTrue(
                (source_tree / "scripts/launch_onyx_live_v19.pyw").is_file()
            )
            self.assertTrue(
                (source_tree / "scripts/bootstrap_onyx_live_v20.pyw").is_file()
            )
            self.assertTrue(
                (source_tree / "scripts/launch_onyx_live_v20.pyw").is_file()
            )
            self.assertTrue(
                (source_tree / "scripts/bootstrap_onyx_live_v21.pyw").is_file()
            )
            self.assertTrue(
                (source_tree / "scripts/launch_onyx_live_v21.pyw").is_file()
            )
            self.assertTrue(
                (source_tree / "scripts/bootstrap_onyx_live_v22.pyw").is_file()
            )
            self.assertTrue(
                (source_tree / "scripts/launch_onyx_live_v22.pyw").is_file()
            )
            self.assertTrue(
                (source_tree / "scripts/bootstrap_onyx_live_v23.pyw").is_file()
            )
            self.assertTrue(
                (source_tree / "scripts/launch_onyx_live_v23.pyw").is_file()
            )
            self.assertTrue((source_tree / "qml/OnyxLiveShellV9.qml").is_file())
            self.assertTrue((source_tree / "qml/OnyxLiveShellV10.qml").is_file())
            self.assertTrue((source_tree / "qml/OnyxLiveShellV11.qml").is_file())
            staged_launcher = source_tree / STAGED_COMPATIBILITY_LAUNCHER
            self.assertTrue(staged_launcher.is_file())
            self.assertEqual(
                sha256(staged_launcher.read_bytes()).hexdigest(),
                COMPATIBILITY_LAUNCHER_SHA256,
            )
            staged_notice = source_tree / STAGED_COMPATIBILITY_NOTICE
            self.assertTrue(staged_notice.is_file())
            self.assertEqual(
                sha256(staged_notice.read_bytes()).hexdigest(),
                COMPATIBILITY_NOTICE_SHA256,
            )
            self.assertIn(
                "PYTHON SOFTWARE FOUNDATION LICENSE", staged_notice.read_text()
            )
            self.assertEqual(tuple(selected_docs), discover_runtime_docs(ROOT))
            self.assertIn(
                "docs/onyx/PHASE11_LOCAL_PROJECT_AUDIT_LIVE_V1.md",
                selected_docs,
            )
            self.assertIn(
                "docs/onyx/operations/"
                "ONYX_V18_DOCUMENT_INTAKE_ACCEPTANCE_2026-07-31.md",
                selected_docs,
            )
            self.assertIn(
                "docs/onyx/operations/ONYX_V19_DAYOPS_ACCEPTANCE_2026-07-31.md",
                selected_docs,
            )
            self.assertIn(
                "docs/onyx/acceptance/VE-HUD-CURRENT-V19-E6-001.manifest.json",
                selected_docs,
            )
            for version in range(20, 26):
                self.assertIn(
                    f"docs/onyx/acceptance/VE-HUD-CURRENT-V{version}-E6-001.manifest.json",
                    selected_docs,
                )
            self.assertNotIn(
                "docs/onyx/rejections/ONYX_LIVE_ACTIVATION_V1_REJECTED.md",
                selected_docs,
            )
            self.assertNotIn(
                "docs/onyx/research/PHASE10_BRAND_PASSPORT_V1_SOURCES.md",
                selected_docs,
            )
            self.assertIn(
                "docs/onyx/rejections/HUD_ORB_V6_VISUAL_REJECTION.md",
                selected_docs,
            )
            self.assertIn(
                "docs/onyx/checkpoints/phase5-capability-nexus-v32/"
                "phase5-capability-nexus-v32.bundle.json",
                selected_docs,
            )
            self.assertFalse(
                any(
                    path.name.endswith((".junit.xml", ".log"))
                    or path.name == "pytest-runtime.zip"
                    for path in docs_tree.rglob("*")
                    if path.is_file()
                )
            )

            for relative in ("main.py", "ui.py", "dashboard/server.py"):
                target = source_tree / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / relative, target)
            verified = v9._verify_runtime_bundle(source_tree)
            self.assertEqual(
                verified["pythonw"],
                (source_tree / STAGED_COMPATIBILITY_LAUNCHER).resolve(),
            )

    def test_clean_checkout_without_local_venv_uses_vendored_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            staging = Path(temporary) / "runtime-sources"
            missing_stdlib = Path(temporary) / "missing-stdlib"
            with patch(
                "scripts.package_hygiene.sysconfig.get_path",
                return_value=str(missing_stdlib),
            ):
                stage_runtime_sources(
                    ROOT,
                    staging,
                    allowed_build_root=Path(temporary),
                )

            launcher = staging / STAGED_COMPATIBILITY_LAUNCHER
            self.assertTrue(launcher.is_file())
            self.assertEqual(
                sha256(launcher.read_bytes()).hexdigest(),
                COMPATIBILITY_LAUNCHER_SHA256,
            )
            notice = staging / STAGED_COMPATIBILITY_NOTICE
            self.assertTrue(notice.is_file())
            self.assertEqual(
                sha256(notice.read_bytes()).hexdigest(),
                COMPATIBILITY_NOTICE_SHA256,
            )
            self.assertFalse((staging / COMPATIBILITY_LAUNCHER_RELATIVE).exists())
            self.assertEqual(package_hygiene_violations(staging), ())
            manifest = json.loads(
                (
                    ROOT / "docs/onyx/checkpoints/onyx-live-activation-v9/"
                    "runtime-manifest.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(
                manifest["files"]["pythonw"]["sha256"],
                COMPATIBILITY_LAUNCHER_SHA256,
            )

    def test_gate_rejects_dev_history_caches_and_legacy_branding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixtures = {
                "core/__pycache__/module.pyc": b"cache",
                "docs/onyx/checkpoints/x/x.junit.xml": b"<xml/>",
                "docs/onyx/checkpoints/x/x.bundle.json": b"{}",
                "docs/onyx/checkpoints/x/private-runtime/pytest-runtime.zip": b"zip",
                "docs/onyx/rejections/old.md": b"old",
                "docs/onyx/research/notes.md": b"notes",
                "docs/onyx/corrections/fix.md": b"fix",
                "scripts/build_dev_evidence.py": b"pass",
                "tests/test_dev_only.py": b"pass",
                "google/genai/tests/test_api.py": b"pass",
                "google/genai/_test_api_client.py": b"pass",
                (
                    "playwright/driver/package/.local-browsers/"
                    "chromium_headless_shell-1228/chrome-headless-shell.exe"
                ): b"binary",
                "docs/onyx/checkpoints/legacy.snapshot": b"Mark-XLVIII",
                "qml/Legacy.qml": b"Jarvis",
            }
            for relative, payload in fixtures.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)
            violations = package_hygiene_violations(root)
            self.assertEqual(len(violations), len(fixtures))
            joined = "\n".join(violations)
            for expected in (
                "Python cache",
                "development evidence",
                "pytest runtime archive",
                "rejection history",
                "research history",
                "correction history",
                "build evidence script",
                "development-only source",
                "third-party development payload",
                "duplicate browser payload",
                "legacy brand token",
            ):
                self.assertIn(expected, joined)

    def test_compatibility_exceptions_are_exact_not_wildcards(self) -> None:
        self.assertEqual(len(RUNTIME_TEST_EVIDENCE_FILES), 3)
        self.assertTrue(all(path.startswith("tests/") for path in RUNTIME_TEST_EVIDENCE_FILES))
        self.assertTrue(set(RUNTIME_TEST_EVIDENCE_FILES) <= COMPATIBILITY_EXCEPTIONS)
        self.assertNotIn("tests", COMPATIBILITY_EXCEPTIONS)
        self.assertNotIn("scripts", COMPATIBILITY_EXCEPTIONS)
        self.assertNotIn("docs/onyx/rejections", COMPATIBILITY_EXCEPTIONS)

    def test_only_exact_aexos_manifest_test_inputs_are_retained(self) -> None:
        self.assertEqual(len(AEXOS_ATTESTED_MANIFEST_FILES), 5)
        self.assertTrue(
            all(
                path.startswith("vendor/aexos-engine-5.3.0/engine/.aexos-core/")
                for path in AEXOS_ATTESTED_MANIFEST_FILES
            )
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative in AEXOS_ATTESTED_MANIFEST_FILES:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("attested inert input", encoding="utf-8")
            unrelated = (
                root
                / "vendor/aexos-engine-5.3.0/engine/.aexos-core/"
                "infrastructure/tests/unrelated.test.js"
            )
            unrelated.write_text("not attested", encoding="utf-8")

            violations = package_hygiene_violations(root)

        self.assertEqual(len(violations), 1)
        self.assertIn("unrelated.test.js", violations[0])
        self.assertIn("third-party development payload", violations[0])

    def test_staging_refuses_project_root_and_ancestor_cleanup(self) -> None:
        with self.assertRaisesRegex(Exception, "unsafe runtime staging destination"):
            stage_runtime_sources(ROOT, ROOT)
        with self.assertRaisesRegex(Exception, "unsafe runtime staging destination"):
            stage_runtime_docs(ROOT, ROOT.parent)
        with tempfile.TemporaryDirectory() as temporary:
            unrelated = Path(temporary) / "runtime-sources"
            with self.assertRaisesRegex(
                Exception, "unsafe runtime staging destination"
            ):
                stage_runtime_sources(ROOT, unrelated)

    def test_staging_refuses_linked_or_reparse_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            allowed = Path(temporary) / "build"
            allowed.mkdir()
            target = allowed / "real-runtime-sources"
            target.mkdir()
            marker = target / "owner-data.txt"
            marker.write_text("preserve", encoding="utf-8")
            linked = allowed / "runtime-sources"
            with patch(
                "scripts.package_hygiene._is_link_like",
                side_effect=lambda candidate: candidate == linked,
            ):
                with self.assertRaisesRegex(
                    Exception, "unsafe linked runtime staging destination"
                ):
                    stage_runtime_sources(
                        ROOT,
                        linked,
                        allowed_build_root=allowed,
                    )
            self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")
            with patch(
                "scripts.package_hygiene._is_link_like",
                side_effect=lambda candidate: candidate == allowed,
            ):
                with self.assertRaisesRegex(
                    Exception, "unsafe linked runtime staging destination"
                ):
                    stage_runtime_sources(
                        ROOT,
                        linked,
                        allowed_build_root=allowed,
                    )
            self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")

    def test_packaged_non_windows_defaults_to_current_portable_contract(self) -> None:
        environment = os.environ.copy()
        environment.pop("ONYX_PORTABLE_CURRENT_ACTIVATION_V1", None)
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import os,platform,runpy,sys;"
                    "sys.frozen=True;"
                    "platform.system=lambda:'Linux';"
                    "ns=runpy.run_path('scripts/bootstrap_onyx.pyw',run_name='portable_contract');"
                    "print(ns['_selected_bootstrap']().name);"
                    "print(os.environ.get('ONYX_PORTABLE_CURRENT_ACTIVATION_V1'))"
                ),
            ],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["bootstrap_onyx_portable_current_v1.pyw", "1"],
        )
        self.assertEqual(result.stderr, "")

    def test_spec_and_build_use_curated_staging_and_post_build_gate(self) -> None:
        spec = (ROOT / "packaging/onyx.spec").read_text(encoding="utf-8")
        build = (ROOT / "scripts/build_release.py").read_text(encoding="utf-8")

        self.assertIn('RUNTIME_SOURCES = ROOT / "build" / "runtime-sources"', spec)
        self.assertIn('str(RUNTIME_SOURCES / "core")', spec)
        self.assertIn('str(RUNTIME_SOURCES / "scripts")', spec)
        self.assertNotIn('str(RUNTIME_SOURCES / "tests")', spec)
        self.assertIn("for relative in RUNTIME_TEST_EVIDENCE_FILES", spec)
        self.assertIn("str(RUNTIME_SOURCES / Path(relative))", spec)
        self.assertIn('str(RUNTIME_SOURCES / "qml")', spec)
        for version in range(20, 26):
            self.assertIn(f'"core.onyx_hud_current_acceptance_v{version}"', spec)
            self.assertIn("VE-HUD-CURRENT-V{version}-E6-001.manifest.json", spec)
        self.assertIn('"core.onyx_hud_current_acceptance_v32"', spec)
        self.assertIn(
            "core/onyx_hud_current_acceptance_v32.py",
            SOURCE_ONLY_HUD_AUTHORITY_FILES,
        )
        self.assertIn("package_native_startup_smoke_test(validation_bundle)", build)
        self.assertIn(
            'str(RUNTIME_SOURCES / ".venv" / "Scripts" / "pythonw.exe")',
            spec,
        )
        self.assertIn(
            "validation_bundle = clone_runtime_validation_bundle(bundle)", build
        )
        self.assertIn("package_governance_smoke_test(validation_bundle)", build)
        self.assertIn("GOVERNANCE_SMOKE_ARGUMENT", build)
        self.assertIn("package_founder_smoke_test(validation_bundle)", build)
        self.assertIn("FOUNDER_SMOKE_ARGUMENT", build)
        self.assertIn("package_document_intake_smoke_test(validation_bundle)", build)
        self.assertIn("clean_path(RUNTIME_VALIDATION_BUNDLE)", build)
        self.assertIn("DOCUMENT_INTAKE_SMOKE_ARGUMENT", build)
        self.assertIn("DOCUMENT_INTAKE_SMOKE_CORPUS_ENV", build)
        self.assertIn("DOCUMENT_INTAKE_SMOKE_OUTPUT_ENV", build)
        self.assertIn(
            'str(RUNTIME_SOURCES / ".venv" / "PSF-LICENSE.txt")',
            spec,
        )
        self.assertNotIn('str(ROOT / "core"), "core"', spec)
        self.assertNotIn('str(ROOT / "scripts"), "scripts"', spec)
        self.assertNotIn('str(ROOT / "tests"', spec)
        self.assertNotIn('str(ROOT / "qml"', spec)
        self.assertNotIn('str(ROOT / ".venv"', spec)
        self.assertIn("_is_development_payload", spec)
        for forbidden_tts in ("edge_tts", "elevenlabs", "kokoro", "pyttsx3"):
            self.assertIn(f'"{forbidden_tts}"', spec)
        for undeclared_heavy in (
            "torch",
            "transformers",
            "sklearn",
            "nltk",
            "pyarrow",
            "scipy",
            "matplotlib",
            "tensorboard",
        ):
            self.assertIn(f'"{undeclared_heavy}"', spec)
        self.assertIn(
            "package_datas if not _is_development_payload(item)",
            spec,
        )
        self.assertIn(
            "package_binaries if not _is_development_payload(item)",
            spec,
        )
        self.assertIn("if not _is_development_module(name)", spec)
        self.assertIn('part.startswith("chromium_headless_shell-")', spec)
        self.assertIn('"google.genai._test_api_client"', spec)
        self.assertIn('vendor" / "aexos-engine-5.3.0"', spec)
        self.assertIn("_append_runtime_tree(", spec)
        self.assertIn('_AEXOS_VENDOR / "engine"', spec)
        self.assertIn('_AEXOS_VENDOR / "runtime"', spec)
        self.assertIn('_AEXOS_VENDOR / "node"', spec)
        self.assertIn("retained_development_paths=_AEXOS_ATTESTED_MANIFEST_FILES", spec)
        self.assertIn("or not _is_development_payload(entry)", spec)
        proprietary_license = (ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("Third-party components", proprietary_license)
        self.assertIn(
            "Python Software Foundation License",
            " ".join(proprietary_license.split()),
        )

        self.assertIn("generate_runtime_docs()", build)
        self.assertIn("generate_runtime_sources()", build)
        self.assertIn("verify_packaged_runtime_hud_contract(", build)
        self.assertIn("assert_safe_build_input_paths(ordered, ROOT)", build)
        self.assertIn("prune_duplicate_browser_payloads(result)", build)
        self.assertIn("assert_embedded_chromium_runtime(result)", build)
        self.assertIn('"--no-shell"', build)
        self.assertGreaterEqual(build.count("assert_package_hygiene("), 3)
        self.assertIn("assert_package_hygiene(result)", build)
        self.assertIn("package_preflight_test(validation_bundle)", build)
        self.assertIn(
            'prefix="onyx-package-preflight-"',
            build,
        )
        self.assertIn(
            "validation_bundle = clone_runtime_validation_bundle(bundle)\n"
            "    try:\n"
            "        with _windows_package_diagnostic_credential_scope():\n"
            "            smoke_test(validation_bundle)\n"
            "            package_preflight_test(validation_bundle)\n"
            "            package_capabilities_smoke_test(validation_bundle)\n"
            "            package_parity_smoke_test(validation_bundle)\n"
            "            package_native_startup_smoke_test(validation_bundle)\n"
            "            if portable_current_gate:\n"
            "                package_portable_current_startup_smoke_test(\n"
            "                    validation_bundle,\n"
            "                    require_secure_backend_probe=(\n"
            "                        args.require_linux_secure_backend_probe\n"
            "                    ),\n"
            "                )\n"
            "            package_governance_smoke_test(validation_bundle)\n"
            "            package_founder_smoke_test(validation_bundle)\n"
            "            package_document_intake_smoke_test(validation_bundle)\n"
            "            package_dayops_smoke_test(validation_bundle)\n"
            "            package_advanced_operations_smoke_test(validation_bundle)\n"
            "            package_advanced_commands_smoke_test(validation_bundle)\n"
            "            package_owner_context_smoke_test(validation_bundle)\n"
            "            package_operational_events_smoke_test(validation_bundle)\n"
            "    finally:\n"
            "        clean_path(RUNTIME_VALIDATION_BUNDLE)\n"
            "    # Runtime validation",
            build,
        )
        self.assertGreaterEqual(build.count("assert_package_hygiene("), 4)
        self.assertIn('"--preflight-only"', build)
        self.assertNotIn("PLATFORM_REFUSAL_EXIT", build)
        self.assertIn("NATIVE_STARTUP_SMOKE_ARGUMENT", build)
        bootstrap = (ROOT / "scripts/bootstrap_onyx.pyw").read_text(encoding="utf-8")
        self.assertIn("sys.dont_write_bytecode = True", bootstrap)
        self.assertIn('PYTHONDONTWRITEBYTECODE", "1"', bootstrap)
        self.assertIn("str(exc) == PLATFORM_REFUSAL_SIGNAL", bootstrap)
        self.assertIn("os._exit(PLATFORM_REFUSAL_EXIT)", bootstrap)
        dayops = (ROOT / "scripts/provision_dayops_v14.py").read_text(encoding="utf-8")
        self.assertIn("sys.dont_write_bytecode = True", dayops)
        self.assertIn('PYTHONDONTWRITEBYTECODE", "1"', dayops)
        installer = (ROOT / "core/installer.py").read_text(encoding="utf-8")
        setup = (ROOT / "setup.py").read_text(encoding="utf-8")
        readiness_probe = (ROOT / "core/readiness_probe.py").read_text(encoding="utf-8")
        self.assertIn('"--no-shell"', installer)
        self.assertIn('"--no-shell"', setup)
        self.assertIn(
            'playwright.chromium.launch(channel="chromium", headless=True)',
            readiness_probe,
        )

    def test_windows_upgrade_replaces_the_entire_frozen_payload_only(self) -> None:
        installer = (ROOT / "packaging/windows/onyx.iss").read_text(encoding="utf-8")
        install_delete = installer.split("[InstallDelete]", 1)[1].split("[Files]", 1)[0]
        self.assertIn('Type: filesandordirs; Name: "{app}\\_internal"', install_delete)
        for relative in ("docs", "tests", "scripts", "core", "Onyx"):
            self.assertIn(f'Name: "{{app}}\\{relative}"', install_delete)
        directives = "\n".join(
            line for line in install_delete.splitlines() if line.startswith("Type:")
        )
        self.assertNotIn("{userappdata}", directives.casefold())
        self.assertNotIn("{localappdata}", directives.casefold())
        self.assertNotIn("Cyryx Labs\\Onyx", directives)
        self.assertNotIn('Name: "{app}\\*"', directives)


if __name__ == "__main__":
    unittest.main()
