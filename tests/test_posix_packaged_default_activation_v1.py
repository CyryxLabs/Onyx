from __future__ import annotations

import runpy
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
STABLE_BOOTSTRAP = ROOT / "scripts" / "bootstrap_onyx.pyw"
PORTABLE_BOOTSTRAP = (
    ROOT / "scripts" / "bootstrap_onyx_portable_current_v1.pyw"
)
PORTABLE_FLAG = "ONYX_PORTABLE_CURRENT_ACTIVATION_V1"


def _stable_namespace() -> dict[str, object]:
    return runpy.run_path(
        str(STABLE_BOOTSTRAP),
        run_name="posix_packaged_default_activation_contract",
    )


def test_windows_keeps_v24_even_when_frozen_or_portable_flag_is_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = _stable_namespace()
    monkeypatch.setattr(namespace["platform"], "system", lambda: "Windows")
    monkeypatch.setattr(namespace["sys"], "frozen", True, raising=False)
    monkeypatch.setenv(PORTABLE_FLAG, "1")

    assert namespace["_selected_bootstrap"]() == namespace["CURRENT_BOOTSTRAP"]
    assert namespace["CURRENT_BOOTSTRAP"].name == "bootstrap_onyx_live_v24.pyw"


@pytest.mark.parametrize("system", ("Darwin", "Linux"))
def test_frozen_posix_defaults_to_portable_without_external_environment(
    system: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = _stable_namespace()
    monkeypatch.setattr(namespace["platform"], "system", lambda: system)
    monkeypatch.setattr(namespace["sys"], "frozen", True, raising=False)
    monkeypatch.delenv(PORTABLE_FLAG, raising=False)

    assert (
        namespace["_selected_bootstrap"]()
        == namespace["PORTABLE_CURRENT_BOOTSTRAP"]
    )
    assert namespace["os"].environ[PORTABLE_FLAG] == "1"


def test_explicit_posix_diagnostic_overrides_remain_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = _stable_namespace()
    monkeypatch.setattr(namespace["platform"], "system", lambda: "Linux")
    monkeypatch.setattr(namespace["sys"], "frozen", False, raising=False)

    monkeypatch.setenv(PORTABLE_FLAG, "1")
    assert (
        namespace["_selected_bootstrap"]()
        == namespace["PORTABLE_CURRENT_BOOTSTRAP"]
    )

    monkeypatch.setattr(namespace["sys"], "frozen", True, raising=False)
    monkeypatch.setenv(PORTABLE_FLAG, "0")
    assert namespace["_selected_bootstrap"]() == namespace["CURRENT_BOOTSTRAP"]


def test_source_posix_default_remains_conservative_and_invalid_override_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = _stable_namespace()
    monkeypatch.setattr(namespace["platform"], "system", lambda: "Darwin")
    monkeypatch.setattr(namespace["sys"], "frozen", False, raising=False)
    monkeypatch.delenv(PORTABLE_FLAG, raising=False)

    assert namespace["_selected_bootstrap"]() == namespace["CURRENT_BOOTSTRAP"]

    monkeypatch.setenv(PORTABLE_FLAG, "yes")
    with pytest.raises(
        RuntimeError,
        match="^ONYX_PORTABLE_CURRENT_V1_SELECTION_INVALID$",
    ):
        namespace["_selected_bootstrap"]()


def test_portable_preflight_still_fails_closed_without_internal_selection() -> None:
    namespace = runpy.run_path(
        str(PORTABLE_BOOTSTRAP),
        run_name="portable_preflight_fail_closed_contract",
    )

    with pytest.raises(
        RuntimeError,
        match="^ONYX_PORTABLE_CURRENT_V1_EXPLICIT_FLAG_REQUIRED$",
    ):
        namespace["_bootstrap_environment"]({})


def test_frozen_posix_package_smoke_uses_portable_environment_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = _stable_namespace()
    monkeypatch.setattr(namespace["platform"], "system", lambda: "Linux")
    monkeypatch.setattr(namespace["sys"], "frozen", True, raising=False)
    monkeypatch.delenv(PORTABLE_FLAG, raising=False)
    observed: dict[str, object] = {}

    def run_path(path: str, *, run_name: str) -> dict[str, object]:
        observed["path"] = Path(path)
        observed["run_name"] = run_name

        def prepare(environ: object) -> dict[str, str]:
            observed["environ"] = environ
            return {PORTABLE_FLAG: "1"}

        return {"_bootstrap_environment": prepare}

    monkeypatch.setattr(namespace["runpy"], "run_path", run_path)
    namespace["_preflight_package_smoke"]()

    assert observed["path"] == namespace["PORTABLE_CURRENT_BOOTSTRAP"]
    assert observed["environ"] is namespace["os"].environ
    assert observed["run_name"] == (
        "onyx_stable_bootstrap_contract_for_package_smoke"
    )


def test_posix_package_launchers_need_no_activation_environment_dependency() -> None:
    desktop = (ROOT / "packaging" / "linux" / "onyx.desktop").read_text(
        encoding="utf-8"
    )
    service = (ROOT / "packaging" / "linux" / "onyx.service").read_text(
        encoding="utf-8"
    )
    launch_agent = (
        ROOT / "packaging" / "macos" / "labs.cyryx.onyx.plist"
    ).read_text(encoding="utf-8")
    spec = (ROOT / "packaging" / "onyx.spec").read_text(encoding="utf-8")

    assert "Exec=/opt/cyryx-labs/onyx/Onyx" in desktop
    assert "ExecStart=/opt/cyryx-labs/onyx/Onyx" in service
    assert "/Applications/Onyx.app/Contents/MacOS/Onyx" in launch_agent
    for source in (desktop, service, launch_agent, spec):
        assert PORTABLE_FLAG not in source
    assert "Environment=" not in service
    assert "EnvironmentVariables" not in launch_agent
