from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts import build_release
from scripts.package_hygiene import CAPABILITY_RUNTIME_FILES
from scripts.verify_release_runtime_closure_v2 import (
    CAPABILITY_HIDDENIMPORTS,
    ReleaseRuntimeClosureV2Error,
    verify_release_runtime_closure_v2,
)


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_FAMILIES = list(build_release.PACKAGED_CAPABILITY_FAMILIES)


def test_packaged_capability_family_gate_matches_the_closed_composition() -> None:
    from core.capability_composition_v1 import CAPABILITY_OPERATIONS

    assert EXPECTED_FAMILIES == sorted(CAPABILITY_OPERATIONS)


def test_runtime_closure_is_exact_explicit_and_test_free() -> None:
    result = verify_release_runtime_closure_v2(ROOT)
    assert result["capability_files"] == list(CAPABILITY_RUNTIME_FILES)
    assert result["hiddenimports"] == list(CAPABILITY_HIDDENIMPORTS)
    assert result["tests_in_runtime"] is False
    assert 'RUNTIME_SOURCES / "tests"' not in (
        ROOT / "packaging/onyx.spec"
    ).read_text(encoding="utf-8")


def test_runtime_closure_rejects_an_unregistered_port(tmp_path: Path) -> None:
    (tmp_path / "core/capability_ports").mkdir(parents=True)
    for relative in CAPABILITY_RUNTIME_FILES:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# bounded fixture\n", encoding="utf-8")
    (tmp_path / "core/capability_ports/extra_v1.py").write_text(
        "# forbidden\n", encoding="utf-8"
    )
    (tmp_path / "packaging").mkdir()
    (tmp_path / "packaging/onyx.spec").write_text(
        "hiddenimports = " + repr(list(CAPABILITY_HIDDENIMPORTS)), encoding="utf-8"
    )
    with pytest.raises(
        ReleaseRuntimeClosureV2Error, match="capability runtime membership drifted"
    ):
        verify_release_runtime_closure_v2(tmp_path)


def test_runtime_closure_rejects_a_missing_port(tmp_path: Path) -> None:
    missing = "core/capability_ports/workspace_v1.py"
    for relative in CAPABILITY_RUNTIME_FILES:
        if relative == missing:
            continue
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# bounded fixture\n", encoding="utf-8")
    (tmp_path / "packaging").mkdir()
    (tmp_path / "packaging/onyx.spec").write_text(
        "hiddenimports = " + repr(list(CAPABILITY_HIDDENIMPORTS)), encoding="utf-8"
    )
    with pytest.raises(
        ReleaseRuntimeClosureV2Error,
        match="required capability runtime input is unavailable",
    ):
        verify_release_runtime_closure_v2(tmp_path)


def test_packaged_capability_smoke_uses_sanitized_external_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    executable = bundle / "Onyx.exe"
    executable.write_bytes(b"frozen")
    observed: dict[str, object] = {}

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        observed.update(argv=argv, **kwargs)
        payload = {
            "schema": "OnyxCapabilitiesCLI.v1",
            "ok": True,
            "command": "safe-test",
            "result": {
                "provider_dispatch": False,
                "families": EXPECTED_FAMILIES,
                "families_denied": EXPECTED_FAMILIES,
                "local_operational": {
                    "families": [
                        "clipboard", "personalization", "plugin", "social", "wellness"
                    ],
                    "publishing": "oauth-adapter-required",
                    "receipts": [
                        {"decision": "allow", "outcome": "dispatched"}
                        for _index in range(9)
                    ],
                },
                "module_origins": {"cli": "scripts/onyx_capabilities_cli.py"},
            },
        }
        return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")

    monkeypatch.setattr(build_release.platform, "system", lambda: "Windows")
    monkeypatch.setattr(build_release.subprocess, "run", run)
    monkeypatch.setenv("GOOGLE_API_KEY", "must-not-cross")
    monkeypatch.setenv("HTTP_PROXY", "must-not-cross")
    result = build_release.package_capabilities_smoke_test(bundle)
    environment = observed["env"]
    assert isinstance(environment, dict)
    assert "GOOGLE_API_KEY" not in environment
    assert "HTTP_PROXY" not in environment
    assert observed["cwd"] != ROOT
    assert observed["argv"] == [str(executable), "--capabilities-smoke-v1"]
    assert result["result"]["families"] == EXPECTED_FAMILIES


def test_packaged_capability_smoke_rejects_missing_required_port(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "Onyx.exe").write_bytes(b"frozen")
    payload = {
        "schema": "OnyxCapabilitiesCLI.v1",
        "ok": True,
        "command": "safe-test",
        "result": {
            "provider_dispatch": False,
            "families": EXPECTED_FAMILIES[:-1],
            "families_denied": EXPECTED_FAMILIES[:-1],
            "module_origins": {"cli": "scripts/onyx_capabilities_cli.py"},
        },
    }
    monkeypatch.setattr(build_release.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        build_release.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, json.dumps(payload), ""
        ),
    )
    with pytest.raises(RuntimeError, match="contract drifted"):
        build_release.package_capabilities_smoke_test(bundle)
