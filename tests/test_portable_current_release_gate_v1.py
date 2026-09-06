from __future__ import annotations

import json
import subprocess
import tarfile
from pathlib import Path

import pytest

from core.native_activation_contract_v1 import activation_contract_for_system_v1
from core.native_startup_smoke_v1 import (
    NATIVE_STARTUP_SMOKE_ARGUMENT,
    NATIVE_STARTUP_SMOKE_CONTRACT,
    NATIVE_STARTUP_SMOKE_OUTPUT_ENV,
    PORTABLE_CURRENT_NEGATIVE_BOUNDARY_GATE,
    TERMINAL_FENCE_EVIDENCE_KEY,
)
from scripts import build_release


def _payload(system: str, *, portable_current: bool) -> dict[str, object]:
    contract = activation_contract_for_system_v1(
        system,
        portable_current=portable_current,
    )
    secure_probe_calls = int(portable_current and system == "Linux")
    payload = {
        "activation": contract["smoke_activation"],
        "activation_contract": contract,
        "activation_profile": contract["activation_profile"],
        "callbacks_bound": not (portable_current and system in {"Darwin", "Linux"}),
        "capability_limited": contract["capability_limited"],
        "contract": NATIVE_STARTUP_SMOKE_CONTRACT,
        "host_constructed": not (portable_current and system in {"Darwin", "Linux"}),
        "interception": {
            "scope": "best_effort_python_runtime",
            "network_surfaces": [
                "network:socket.getaddrinfo",
                "network:socket.socket.send",
                "network:socket.socket.sendall",
                "network:socket.socket.sendto",
            ],
            "process_surfaces": ["process:subprocess.Popen"],
            "provider_surfaces": ["provider:google.genai.Client"],
            "secure_backend_probe_calls": secure_probe_calls,
            "secure_backend_probe_surfaces": (
                ["process:subprocess.run:posix_owner_backend_read_only"]
                if secure_probe_calls
                else []
            ),
        },
        "network_calls": 0,
        "process_calls": 0,
        "provider_calls": 0,
        "secure_backend_probe_calls": secure_probe_calls,
        "real_ui": not (portable_current and system in {"Darwin", "Linux"}),
        "status": (
            "passed_limited"
            if portable_current and system in {"Darwin", "Linux"}
            else "passed"
        ),
        "system": system,
        TERMINAL_FENCE_EVIDENCE_KEY: True,
        "ui_renderer": (
            "not_started_fail_closed"
            if portable_current and system in {"Darwin", "Linux"}
            else "cinematic-v5"
        ),
        "window_visible": not (portable_current and system in {"Darwin", "Linux"}),
    }
    if portable_current and system in {"Darwin", "Linux"}:
        payload.update(
            {
                "declared_activation": "v19",
                "highest_proven_activation": "v16_descriptor_ledger",
                "boundary_reached": "pre_v10",
                "evidence_scope": PORTABLE_CURRENT_NEGATIVE_BOUNDARY_GATE,
                "limitation_reason": (
                    "portable_current_v4_owner_authority_unavailable"
                ),
                "next_unimplemented_activation": "v4_portable_owner_authority",
                "native_evidence_required": True,
                "safe_unavailability": True,
                "v15_v19_parity": False,
            }
        )
    return payload


def _write_smoke_output(
    kwargs: dict[str, object],
    payload: dict[str, object],
) -> subprocess.CompletedProcess[str]:
    environment = kwargs["env"]
    assert isinstance(environment, dict)
    output = Path(environment[NATIVE_STARTUP_SMOKE_OUTPUT_ENV])
    output.write_text(json.dumps(payload), encoding="utf-8")
    return subprocess.CompletedProcess([], 0, "", "")


def test_baseline_gate_selects_explicit_posix_predecessor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "Onyx"
    executable.touch()
    observed: dict[str, str] = {}
    monkeypatch.setenv(build_release.PORTABLE_CURRENT_ACTIVATION_ENV, "1")

    def run(argv, **kwargs):
        assert argv == [str(executable), NATIVE_STARTUP_SMOKE_ARGUMENT]
        observed.update(kwargs["env"])
        return _write_smoke_output(kwargs, _payload("Linux", portable_current=False))

    monkeypatch.setattr(build_release.subprocess, "run", run)

    result = build_release.package_native_startup_executable_smoke_test(
        executable,
        system="Linux",
    )

    assert observed[build_release.PORTABLE_CURRENT_ACTIVATION_ENV] == "0"
    assert result["activation_profile"] == "portable-v8-fallback-capability-limited"


def test_package_preflight_selects_explicit_posix_predecessor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "Onyx").touch()
    observed: list[dict[str, str]] = []
    monkeypatch.setenv(build_release.PORTABLE_CURRENT_ACTIVATION_ENV, "1")
    monkeypatch.setattr(build_release.platform, "system", lambda: "Linux")

    def run(_argv, **kwargs):
        observed.append(dict(kwargs["env"]))
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(build_release.subprocess, "run", run)
    build_release.package_preflight_test(bundle)

    assert len(observed) == 1
    assert observed[0][build_release.PORTABLE_CURRENT_ACTIVATION_ENV] == "0"


def test_negative_boundary_gate_is_explicit_and_injects_exact_child_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "Onyx"
    executable.touch()

    observed: dict[str, str] = {}
    monkeypatch.setenv(build_release.PORTABLE_CURRENT_ACTIVATION_ENV, "ambient")

    def run(_argv, **kwargs):
        observed.update(kwargs["env"])
        return _write_smoke_output(kwargs, _payload("Linux", portable_current=True))

    monkeypatch.setattr(build_release.subprocess, "run", run)
    result = build_release.package_portable_current_startup_executable_smoke_test(
        executable,
        system="Linux",
    )

    assert result["evidence_scope"] == PORTABLE_CURRENT_NEGATIVE_BOUNDARY_GATE
    assert observed[build_release.PORTABLE_CURRENT_ACTIVATION_ENV] == "1"

    with pytest.raises(RuntimeError, match="requires a POSIX host"):
        build_release.package_portable_current_startup_executable_smoke_test(
            executable,
            system="Windows",
        )


def test_candidate_gate_validates_explicit_limited_profile_without_windows_log(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "Onyx"
    executable.touch()
    observed: dict[str, str] = {}
    monkeypatch.setenv(build_release.PORTABLE_CURRENT_ACTIVATION_ENV, "1")

    def run(_argv, **kwargs):
        observed.update(kwargs["env"])
        return _write_smoke_output(kwargs, _payload("Linux", portable_current=True))

    monkeypatch.setattr(build_release.subprocess, "run", run)

    result = build_release.package_portable_current_startup_executable_smoke_test(
        executable,
        system="Linux",
    )

    assert observed[build_release.PORTABLE_CURRENT_ACTIVATION_ENV] == "1"
    assert result["activation_profile"] == (
        "portable-current-negative-boundary-default-off"
    )
    assert result["capability_limited"] is True
    assert result["evidence_scope"] == "portable_current_negative_boundary_gate"
    assert result["safe_unavailability"] is True
    assert result["host_constructed"] is False
    assert result["activation_contract"]["v15_v19_parity"] is False
    assert result["activation_contract"]["native_evidence_required"] is True


def test_diagnostic_candidate_accepts_zero_when_helper_is_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "Onyx"
    executable.touch()

    def run(_argv, **kwargs):
        payload = _payload("Linux", portable_current=True)
        payload["secure_backend_probe_calls"] = 0
        interception = payload["interception"]
        assert isinstance(interception, dict)
        interception["secure_backend_probe_calls"] = 0
        interception["secure_backend_probe_surfaces"] = []
        return _write_smoke_output(kwargs, payload)

    monkeypatch.setattr(build_release.subprocess, "run", run)
    result = build_release.package_portable_current_startup_executable_smoke_test(
        executable,
        system="Linux",
    )
    assert result["secure_backend_probe_calls"] == 0


def test_official_linux_candidate_rejects_forged_zero_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "Onyx"
    executable.touch()

    def run(_argv, **kwargs):
        payload = _payload("Linux", portable_current=True)
        payload["secure_backend_probe_calls"] = 0
        interception = payload["interception"]
        assert isinstance(interception, dict)
        interception["secure_backend_probe_calls"] = 0
        interception["secure_backend_probe_surfaces"] = []
        return _write_smoke_output(kwargs, payload)

    monkeypatch.setattr(build_release.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="secure-backend probe evidence"):
        build_release.package_portable_current_startup_executable_smoke_test(
            executable,
            system="Linux",
            require_secure_backend_probe=True,
        )


def test_official_linux_candidate_accepts_observed_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "Onyx"
    executable.touch()
    monkeypatch.setattr(
        build_release.subprocess,
        "run",
        lambda _argv, **kwargs: _write_smoke_output(
            kwargs,
            _payload("Linux", portable_current=True),
        ),
    )
    result = build_release.package_portable_current_startup_executable_smoke_test(
        executable,
        system="Linux",
        require_secure_backend_probe=True,
    )
    assert result["secure_backend_probe_calls"] == 1


def test_linux_candidate_rejects_boolean_alias_for_probe_count(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "Onyx"
    executable.touch()

    def run(_argv, **kwargs):
        payload = _payload("Linux", portable_current=True)
        interception = payload["interception"]
        assert isinstance(interception, dict)
        interception["secure_backend_probe_calls"] = True
        return _write_smoke_output(kwargs, payload)

    monkeypatch.setattr(build_release.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="secure-backend probe evidence"):
        build_release.package_portable_current_startup_executable_smoke_test(
            executable,
            system="Linux",
            require_secure_backend_probe=True,
        )


@pytest.mark.parametrize(
    ("system", "portable_current"),
    (("Windows", True), ("Darwin", True), ("Linux", False)),
)
def test_secure_probe_requirement_rejects_cli_misuse(
    system: str,
    portable_current: bool,
) -> None:
    with pytest.raises(RuntimeError, match="probe requirement"):
        build_release.validate_secure_backend_probe_requirement(
            require=True,
            portable_current=portable_current,
            system=system,
        )


@pytest.mark.parametrize(
    ("portable_current", "require_probe", "policy", "message"),
    (
        (False, True, "unsigned-approved", "portable-current"),
        (True, False, "unsigned-approved", "secure-backend probe"),
        (True, True, None, "linux-signing-policy unsigned-approved"),
    ),
)
def test_formal_linux_cli_rejects_each_missing_publication_gate(
    portable_current: bool,
    require_probe: bool,
    policy: str | None,
    message: str,
) -> None:
    with pytest.raises(RuntimeError, match=message):
        build_release.validate_formal_linux_release_contract(
            formal_release=True,
            system="Linux",
            portable_current=portable_current,
            require_secure_backend_probe=require_probe,
            linux_signing_policy=policy,
        )


def test_complete_formal_linux_cli_contract_is_accepted() -> None:
    build_release.validate_formal_linux_release_contract(
        formal_release=True,
        system="Linux",
        portable_current=True,
        require_secure_backend_probe=True,
        linux_signing_policy="unsigned-approved",
    )


def test_formal_linux_contract_runs_before_release_mutation() -> None:
    source = Path(build_release.__file__).read_text(encoding="utf-8")
    main = source.split("def main() -> int:", 1)[1]
    assert main.index("validate_formal_linux_release_contract(") < main.index(
        "archive_existing_release()"
    )


def test_candidate_gate_rejects_baseline_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "Onyx"
    executable.touch()
    monkeypatch.setenv(build_release.PORTABLE_CURRENT_ACTIVATION_ENV, "1")
    monkeypatch.setattr(
        build_release.subprocess,
        "run",
        lambda _argv, **kwargs: _write_smoke_output(
            kwargs,
            _payload("Linux", portable_current=False),
        ),
    )

    with pytest.raises(
        RuntimeError,
        match="startup smoke result is invalid|portable-current native evidence is invalid",
    ):
        build_release.package_portable_current_startup_executable_smoke_test(
            executable,
            system="Linux",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("highest_proven_activation", "v15"),
        ("boundary_reached", "v15"),
        ("next_unimplemented_activation", "v17"),
        ("limitation_reason", "portable_current_unavailable"),
        ("declared_activation", "v15"),
        ("evidence_scope", "host_activation_evidence"),
        ("safe_unavailability", False),
        ("status", "passed"),
    ],
)
def test_candidate_gate_rejects_dishonest_limited_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    executable = tmp_path / "Onyx"
    executable.touch()
    monkeypatch.setenv(build_release.PORTABLE_CURRENT_ACTIVATION_ENV, "1")

    def run(_argv, **kwargs):
        payload = _payload("Linux", portable_current=True)
        payload[field] = value
        return _write_smoke_output(kwargs, payload)

    monkeypatch.setattr(build_release.subprocess, "run", run)
    with pytest.raises(
        RuntimeError,
        match="startup smoke result is invalid|portable-current native evidence is invalid",
    ):
        build_release.package_portable_current_startup_executable_smoke_test(
            executable,
            system="Linux",
        )


@pytest.mark.parametrize("tamper", ("count", "surface", "overflow"))
def test_candidate_gate_rejects_forged_secure_backend_probe_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
) -> None:
    executable = tmp_path / "Onyx"
    executable.touch()

    def run(_argv, **kwargs):
        payload = _payload("Linux", portable_current=True)
        interception = payload["interception"]
        assert isinstance(interception, dict)
        if tamper == "count":
            interception["secure_backend_probe_calls"] = 0
        elif tamper == "surface":
            interception["secure_backend_probe_surfaces"] = ["process:any"]
        else:
            payload["secure_backend_probe_calls"] = 6
            interception["secure_backend_probe_calls"] = 6
        return _write_smoke_output(kwargs, payload)

    monkeypatch.setattr(build_release.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="secure-backend probe evidence"):
        build_release.package_portable_current_startup_executable_smoke_test(
            executable,
            system="Linux",
        )


def test_candidate_artifact_gate_executes_deb_tar_and_single_formal_appimage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = tmp_path / "Onyx.deb"
    package.touch()
    archive = tmp_path / "Onyx.tar.gz"
    tar_source = tmp_path / "tar-source" / "Onyx"
    tar_source.mkdir(parents=True)
    (tar_source / "Onyx").touch()
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(tar_source, arcname="Onyx")
    appimages = [tmp_path / "Onyx.AppImage"]
    for appimage in appimages:
        appimage.touch()
    monkeypatch.setenv(build_release.PORTABLE_CURRENT_ACTIVATION_ENV, "1")
    calls: list[tuple[Path, str, dict[str, str] | None]] = []

    def extract(argv, **_kwargs):
        destination = Path(argv[-1])
        bundle = destination / "opt" / "cyryx-labs" / "onyx"
        bundle.mkdir(parents=True)
        (bundle / "Onyx").touch()
        return subprocess.CompletedProcess(argv, 0, "", "")

    def bundle_smoke(bundle: Path) -> dict[str, object]:
        calls.append((bundle / "Onyx", "bundle", None))
        return _payload("Linux", portable_current=True)

    def executable_smoke(
        executable: Path,
        *,
        system: str,
        extra_environment: dict[str, str] | None = None,
    ) -> dict[str, object]:
        calls.append((executable, system, extra_environment))
        return _payload(system, portable_current=True)

    monkeypatch.setattr(build_release.subprocess, "run", extract)
    monkeypatch.setattr(
        build_release,
        "package_portable_current_startup_smoke_test",
        bundle_smoke,
    )
    monkeypatch.setattr(
        build_release,
        "package_portable_current_startup_executable_smoke_test",
        executable_smoke,
    )

    build_release.package_artifact_entrypoint_smoke_test(
        [package, archive, *appimages],
        system="Linux",
        portable_current=True,
    )

    assert calls[0][1] == "bundle"
    assert calls[1][1] == "bundle"
    assert calls[2:] == [
        (appimages[0], "Linux", {"APPIMAGE_EXTRACT_AND_RUN": "1"}),
    ]


def test_native_release_workflow_selects_negative_gate_without_ambient_flag() -> None:
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "release-packages.yml"
    ).read_text(encoding="utf-8")

    assert "--portable-current-negative-boundary-gate" in workflow
    assert "ONYX_PORTABLE_CURRENT_ACTIVATION_V1:" not in workflow


def test_official_linux_runner_requires_trusted_secret_tool_probe() -> None:
    runner = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "run_linux_release_validation.sh"
    ).read_text(encoding="utf-8")

    assert "from core.native_vault import _linux_secret_tool" in runner
    assert "--require-linux-secure-backend-probe" in runner
    assert "--portable-current-negative-boundary-gate" in runner


def test_release_workflow_formal_linux_path_is_complete_and_pinned() -> None:
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "release-packages.yml"
    ).read_text(encoding="utf-8")

    assert 'candidate="$(apt-cache policy libsecret-tools' in workflow
    assert '"libsecret-tools=$candidate"' in workflow
    assert workflow.count(
        "from core.native_vault import _linux_secret_tool"
    ) >= 2
    assert "gate_args+=(--formal-release)" in workflow
    assert "--portable-current-negative-boundary-gate" in workflow
    assert "--require-linux-secure-backend-probe" in workflow
    assert "--linux-signing-policy unsigned-approved" in workflow
    assert 'python scripts/build_release.py --version "$version"' in workflow
