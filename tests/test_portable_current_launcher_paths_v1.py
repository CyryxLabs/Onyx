from __future__ import annotations

import os
import runpy
from pathlib import Path

import pytest

from core import paths


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts" / "launch_onyx_portable_current_v1.pyw"
BOOTSTRAP = ROOT / "scripts" / "bootstrap_onyx_portable_current_v1.pyw"


def _load(path: Path) -> dict[str, object]:
    return runpy.run_path(str(path), run_name=f"_test_{path.stem}")


def test_both_portable_current_launchers_delegate_override_validation() -> None:
    launcher_source = LAUNCHER.read_text(encoding="utf-8")
    bootstrap_source = BOOTSTRAP.read_text(encoding="utf-8")

    for source in (launcher_source, bootstrap_source):
        assert 'os.environ.get("ONYX_DATA_DIR"' not in source
        assert "Path(override)" not in source
        assert "data_root()" in source
        assert "private_control_plane_runtime_dir()" in source


@pytest.mark.skipif(os.name != "posix", reason="native POSIX path contract")
@pytest.mark.parametrize(
    "configured",
    [
        "/etc/Onyx",
        "/usr/local/Onyx",
        "/var/lib/Onyx",
        "/opt/Cyryx/Onyx",
        "/run/user/Onyx",
        "/",
    ],
)
def test_both_launchers_reject_untrusted_configured_roots(
    configured: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launcher = _load(LAUNCHER)
    bootstrap = _load(BOOTSTRAP)
    monkeypatch.setenv("ONYX_DATA_DIR", configured)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)

    with pytest.raises(paths.PrivateDataPathError):
        launcher["_portable_runtime_root"]()
    with pytest.raises(paths.PrivateDataPathError):
        bootstrap["_portable_workspace_base"]()


@pytest.mark.skipif(os.name != "posix", reason="native POSIX symlink contract")
def test_both_launchers_reject_configured_root_with_linked_ancestor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launcher = _load(LAUNCHER)
    bootstrap = _load(BOOTSTRAP)
    outside = tmp_path / "outside"
    outside.mkdir()
    linked = tmp_path / "redirect"
    linked.symlink_to(outside, target_is_directory=True)
    monkeypatch.setenv("ONYX_DATA_DIR", str(linked / "Onyx"))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)

    with pytest.raises(paths.PrivateDataPathError, match="component is linked"):
        launcher["_portable_runtime_root"]()
    with pytest.raises(paths.PrivateDataPathError, match="component is linked"):
        bootstrap["_portable_workspace_base"]()


@pytest.mark.skipif(os.name != "posix", reason="native POSIX path contract")
def test_both_launchers_accept_private_configured_leaf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launcher = _load(LAUNCHER)
    bootstrap = _load(BOOTSTRAP)
    configured = tmp_path / "private" / "Onyx"
    monkeypatch.setenv("ONYX_DATA_DIR", str(configured))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)

    assert launcher["_portable_runtime_root"]() == configured / "runtime"
    assert bootstrap["_portable_workspace_base"]() == configured


@pytest.mark.skipif(os.name != "posix", reason="native POSIX XDG contract")
@pytest.mark.parametrize(
    "configured",
    [
        "/etc/onyx-data",
        "/usr/local/share",
        "/var/lib",
        "/opt/cyryx",
        "/run/user",
        "/",
        "relative-data",
    ],
)
def test_private_control_plane_rejects_untrusted_xdg_data_home(
    configured: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(paths.platform, "system", lambda: "Linux")
    monkeypatch.setenv("XDG_DATA_HOME", configured)

    with pytest.raises(paths.PrivateDataPathError):
        paths.private_control_plane_runtime_dir()


@pytest.mark.skipif(os.name != "posix", reason="native POSIX XDG symlink contract")
def test_private_control_plane_rejects_xdg_linked_ancestor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    linked = tmp_path / "redirect"
    linked.symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(paths.platform, "system", lambda: "Linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(linked / "data"))

    with pytest.raises(paths.PrivateDataPathError, match="component is linked"):
        paths.private_control_plane_runtime_dir()


@pytest.mark.skipif(os.name != "posix", reason="native POSIX XDG path contract")
def test_private_control_plane_accepts_private_xdg_data_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = tmp_path / "xdg-data"
    monkeypatch.setattr(paths.platform, "system", lambda: "Linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(configured))

    assert paths.private_control_plane_runtime_dir() == (
        configured / "cyryx-labs" / "onyx" / "runtime"
    )
