from __future__ import annotations

from collections.abc import Callable
import runpy
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "scripts" / "bootstrap_onyx.pyw"
V24_BOOTSTRAP = ROOT / "scripts" / "bootstrap_onyx_live_v24.pyw"


def _contract() -> dict[str, object]:
    return runpy.run_path(str(BOOTSTRAP), run_name="onyx_bootstrap_empty_argv_contract")


def _v24_contract() -> dict[str, object]:
    return runpy.run_path(
        str(V24_BOOTSTRAP), run_name="onyx_v24_bootstrap_empty_argv_contract"
    )


@pytest.mark.parametrize("contract_factory", (_contract, _v24_contract))
@pytest.mark.parametrize("argument", ("", '\"\"'))
def test_windows_empty_shortcut_argument_is_normalized(
    monkeypatch: pytest.MonkeyPatch,
    contract_factory: Callable[[], dict[str, object]],
    argument: str,
) -> None:
    contract = contract_factory()
    argv = contract["sys"].argv
    monkeypatch.setattr(contract["platform"], "system", lambda: "Windows")
    original = list(argv)
    try:
        argv[:] = ["Onyx.exe", argument]
        contract["_normalize_windows_empty_launch_arguments"]()
        assert argv == ["Onyx.exe"]
    finally:
        argv[:] = original


@pytest.mark.parametrize("argument", [" ", "--unknown", "--preflight-only "])
@pytest.mark.parametrize("contract_factory", (_contract, _v24_contract))
def test_nonempty_arguments_are_never_normalized(
    monkeypatch: pytest.MonkeyPatch,
    contract_factory: Callable[[], dict[str, object]],
    argument: str,
) -> None:
    contract = contract_factory()
    argv = contract["sys"].argv
    monkeypatch.setattr(contract["platform"], "system", lambda: "Windows")
    original = list(argv)
    try:
        argv[:] = ["Onyx.exe", argument]
        contract["_normalize_windows_empty_launch_arguments"]()
        assert argv == ["Onyx.exe", argument]
    finally:
        argv[:] = original


@pytest.mark.parametrize("contract_factory", (_contract, _v24_contract))
def test_non_windows_empty_argument_is_not_normalized(
    monkeypatch: pytest.MonkeyPatch,
    contract_factory: Callable[[], dict[str, object]],
) -> None:
    contract = contract_factory()
    argv = contract["sys"].argv
    monkeypatch.setattr(contract["platform"], "system", lambda: "Linux")
    original = list(argv)
    try:
        argv[:] = ["Onyx", ""]
        contract["_normalize_windows_empty_launch_arguments"]()
        assert argv == ["Onyx", ""]
    finally:
        argv[:] = original


@pytest.mark.parametrize(
    "arguments",
    [
        ["", "--preflight-only"],
        ["--preflight-only", ""],
        ["", ""],
        ['""', '""'],
        ['""', "--preflight-only"],
    ],
)
@pytest.mark.parametrize("contract_factory", (_contract, _v24_contract))
def test_empty_argument_is_only_normalized_for_exact_desktop_launch(
    monkeypatch: pytest.MonkeyPatch,
    contract_factory: Callable[[], dict[str, object]],
    arguments: list[str],
) -> None:
    contract = contract_factory()
    argv = contract["sys"].argv
    monkeypatch.setattr(contract["platform"], "system", lambda: "Windows")
    original = list(argv)
    try:
        argv[:] = ["Onyx.exe", *arguments]
        contract["_normalize_windows_empty_launch_arguments"]()
        assert argv == ["Onyx.exe", *arguments]
    finally:
        argv[:] = original


def test_installer_deletes_stale_desktop_shortcut_before_recreation() -> None:
    installer = (ROOT / "packaging" / "windows" / "onyx.iss").read_text(
        encoding="utf-8"
    )
    install_delete = installer.split("[InstallDelete]", 1)[1].split("[Files]", 1)[0]
    assert 'Type: files; Name: "{autodesktop}\\Onyx.lnk"' in install_delete
    icon_contract = installer.split("[Icons]", 1)[1].split("[Registry]", 1)[0]
    desktop_line = next(
        line for line in icon_contract.splitlines() if '"{autodesktop}\\Onyx"' in line
    )
    assert "Parameters:" not in desktop_line
