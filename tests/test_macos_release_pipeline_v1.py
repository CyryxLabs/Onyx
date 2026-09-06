from __future__ import annotations

import ast
import plistlib
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import macos_lifecycle_validation as lifecycle
from scripts import macos_release


ROOT = Path(__file__).resolve().parents[1]


def test_supported_macos_matrix_is_explicit_and_native() -> None:
    assert macos_release.MACOS_MINIMUM_VERSION == "15.0"
    assert macos_release.supported_architecture("arm64") == "arm64"
    for unsupported in ("x86_64", "universal2"):
        with pytest.raises(macos_release.MacReleaseError, match="unsupported"):
            macos_release.supported_architecture(unsupported)


def test_formal_environment_fails_closed_and_binds_identity_to_team(
    tmp_path: Path,
) -> None:
    with pytest.raises(macos_release.MacReleaseError, match="incomplete"):
        macos_release.require_formal_environment({})

    keychain = tmp_path / "onyx.keychain-db"
    notary_key = tmp_path / "AuthKey.p8"
    keychain.write_bytes(b"keychain")
    notary_key.write_bytes(b"notary")
    valid = {
        "APPLE_TEAM_ID": "ABC123DEFG",
        "APPLE_SIGNING_IDENTITY": (
            "Developer ID Application: Cyryx Labs LLC (ABC123DEFG)"
        ),
        "APPLE_KEYCHAIN_PATH": str(keychain),
        "APPLE_NOTARY_KEY_PATH": str(notary_key),
        "APPLE_NOTARY_KEY_ID": "KEY123ABCD",
        "APPLE_NOTARY_ISSUER_ID": "12345678-1234-1234-1234-123456789abc",
    }
    assert macos_release.require_formal_environment(valid)["APPLE_TEAM_ID"] == "ABC123DEFG"
    drifted = {**valid, "APPLE_SIGNING_IDENTITY": "Developer ID Application: Other (ZZZ123DEFG)"}
    with pytest.raises(macos_release.MacReleaseError, match="not bound"):
        macos_release.require_formal_environment(drifted)


def test_spec_declares_truthful_macos_15_floor() -> None:
    spec = (ROOT / "packaging" / "onyx.spec").read_text(encoding="utf-8")
    assert 'MACOS_MINIMUM_VERSION = os.environ.get("MACOSX_DEPLOYMENT_TARGET", "15.0")' in spec
    assert '"LSMinimumSystemVersion": MACOS_MINIMUM_VERSION' in spec
    assert '"12.0"' not in spec


def test_parent_and_browser_entitlements_are_separated() -> None:
    parent = plistlib.loads(
        (ROOT / "packaging" / "macos" / "entitlements.plist").read_bytes()
    )
    browser = plistlib.loads(
        (ROOT / "packaging" / "macos" / "browser-entitlements.plist").read_bytes()
    )
    assert parent["com.apple.security.device.audio-input"] is True
    assert parent["com.apple.security.device.camera"] is True
    assert parent["com.apple.security.automation.apple-events"] is True
    assert "com.apple.security.cs.allow-jit" not in parent
    assert browser == {
        "com.apple.security.cs.allow-jit": True,
        "com.apple.security.cs.allow-unsigned-executable-memory": True,
    }


def test_cryptography_lock_uses_security_fixed_arm64_line() -> None:
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    lock = (ROOT / "requirements.lock").read_text(encoding="utf-8")
    assert re.search(r"^cryptography>=48\.0\.1$", requirements, re.MULTILINE)
    match = re.search(
        r"^cryptography==50\.0\.0 \\\n(?P<body>(?:    --hash=sha256:[0-9a-f]{64}(?: \\\n|\n))+)",
        lock,
        re.MULTILINE,
    )
    assert match is not None
    assert match.group("body").count("--hash=sha256:") >= 40
    assert "cryptography==46.0.7" not in lock


def test_release_workflow_is_fail_closed_and_destroys_keychain() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release-packages.yml").read_text(
        encoding="utf-8"
    )
    for secret in (
        "APPLE_TEAM_ID",
        "APPLE_DEVELOPER_ID_P12_BASE64",
        "APPLE_DEVELOPER_ID_P12_PASSWORD",
        "APPLE_NOTARY_KEY_P8_BASE64",
        "APPLE_NOTARY_KEY_ID",
        "APPLE_NOTARY_ISSUER_ID",
    ):
        assert f"secrets.{secret}" in workflow
    for gate in (
        "--only-binary=cryptography",
        "--formal-release",
        "security create-keychain",
        "security import",
        "security set-key-partition-list",
        "security delete-keychain",
        "generate_release_sbom.py",
    ):
        assert gate in workflow
    assert "macos-15" in workflow
    assert "macos-15-intel" not in workflow
    assert 'MACOSX_DEPLOYMENT_TARGET: "15.0"' in workflow
    assert "if: always() && runner.os == 'macOS'" in workflow


def test_release_module_wires_inside_out_notary_staple_and_gatekeeper() -> None:
    source = (ROOT / "scripts" / "macos_release.py").read_text(encoding="utf-8")
    for contract in (
        "sign_app_inside_out",
        '"--options", "runtime"',
        '"--timestamp"',
        '"notarytool"',
        '"--wait"',
        '"stapler"',
        '"spctl"',
        '"hdiutil"',
        '"codesign"',
        "notary-log-",
        "notary-submit-",
        "macos-release-evidence-",
        '"developer_id_identity"',
        '"team_id"',
    ):
        assert contract in source
    signing = source[source.index("def sign_app_inside_out"):source.index("def verify_signed_app")]
    assert '"--deep"' not in signing


def test_build_release_marks_adhoc_macos_as_diagnostic() -> None:
    source = (ROOT / "scripts" / "build_release.py").read_text(encoding="utf-8")
    assert '"macos_adhoc_not_notarized"' in source
    assert "formal_release=args.formal_release" in source
    # Check the real signing-policy expression, independent of line wrapping.
    assignments = [
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "signing_policy"
                for target in node.targets)
    ]
    assert len(assignments) == 1
    expression = ast.Expression(assignments[0].value)
    for formal, expected in ((True, "developer-id-notarized"),
                             (False, "adhoc-untrusted")):
        result = eval(compile(expression, "build_release.py", "eval"),
                      {"__builtins__": {}},
                      {"system": "Darwin", "args": SimpleNamespace(
                          formal_release=formal, linux_signing_policy=None)})
        assert result == expected


def test_lifecycle_requires_disposable_host_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lifecycle, "assert_supported_host", lambda: "arm64")
    with pytest.raises(lifecycle.MacLifecycleError, match="disposable-host token"):
        lifecycle.require_disposable_host({})
    lifecycle.require_disposable_host(
        {"ONYX_DISPOSABLE_MAC_CONFIRM": lifecycle.CONFIRMATION}
    )


def test_lifecycle_contract_covers_clean_upgrade_uninstall_reinstall_rollback() -> None:
    source = (ROOT / "scripts" / "macos_lifecycle_validation.py").read_text(
        encoding="utf-8"
    )
    for gate in (
        "clean_install_current",
        "uninstall_app_only",
        "reinstall_current",
        "upgrade_prior_to_current",
        "rollback_current_to_prior",
        "owner-data-backup",
        "com.apple.quarantine",
        "/Applications/Onyx.app",
        "onyx.macos-lifecycle-evidence.v1",
        "labs.cyryx.onyx.plist",
        '"launchctl", "bootstrap"',
        '"launchctl", "bootout"',
    ):
        assert gate in source
    assert "shutil.rmtree(APP.parent)" not in source
    assert "shutil.rmtree(Path.home())" not in source


def test_documented_evidence_boundary_does_not_claim_real_mac_completion() -> None:
    story = (ROOT / "docs" / "stories" / "ONYX-REL-MACOS-1.1.8.md").read_text(
        encoding="utf-8"
    )
    assert "does not establish a macOS build" in story
    assert "Real-Mac" in story
