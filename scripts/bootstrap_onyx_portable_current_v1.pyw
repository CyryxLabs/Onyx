"""Default-off bootstrap for the current Onyx stack on macOS and Linux."""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path


ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])).resolve()
LAUNCHER = ROOT / "scripts" / "launch_onyx_portable_current_v1.pyw"
_WORKSPACE_BOUNDARIES: list[object] = []


def _portable_workspace_base() -> Path:
    """Select a centrally validated private root without parsing overrides here."""

    from core.paths import (
        data_root,
        is_frozen,
        private_control_plane_runtime_dir,
        resource_root,
    )

    if os.name != "posix":
        raise RuntimeError("ONYX_PORTABLE_CURRENT_V1_POSIX_HOST_REQUIRED")
    configured = data_root()
    if is_frozen() or configured != resource_root():
        return configured
    return private_control_plane_runtime_dir()


def _default_workspace_root() -> Path:
    from core.posix_trusted_directory_v1 import PosixTrustedDirectoryV1

    base = _portable_workspace_base()
    boundary = PosixTrustedDirectoryV1(root=base / "workspace", enabled=True)
    _WORKSPACE_BOUNDARIES.append(boundary)
    return boundary.path


def _bootstrap_environment(
    environ: dict[str, str] | os._Environ[str],
) -> dict[str, str]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from core import onyx_live_activation_v19 as v19
    from core.onyx_portable_current_activation_v1 import (
        FEATURE_FLAG,
        exact_activation_environment_v1,
    )

    if environ.get(FEATURE_FLAG) != "1":
        raise RuntimeError("ONYX_PORTABLE_CURRENT_V1_EXPLICIT_FLAG_REQUIRED")
    if any(name in environ for name in v19.CONTROL_FLAGS):
        raise RuntimeError("ONYX_PORTABLE_CURRENT_V1_PARTIAL_CONFIGURATION_REFUSED")
    workspace = _default_workspace_root()
    boundary = _WORKSPACE_BOUNDARIES[-1] if os.name == "posix" else None
    return exact_activation_environment_v1(
        workspace,
        environ=environ,
        workspace_boundary=boundary,
    )


def run() -> None:
    if tuple(sys.argv[1:]) not in (
        (),
        ("--preflight-only",),
        ("--native-startup-smoke-test",),
    ):
        raise RuntimeError("Onyx portable-current bootstrap arguments are invalid")
    prepared = _bootstrap_environment(os.environ)
    os.environ.clear()
    os.environ.update(prepared)
    os.chdir(ROOT)
    try:
        runpy.run_path(str(LAUNCHER), run_name="__main__")
    finally:
        while _WORKSPACE_BOUNDARIES:
            boundary = _WORKSPACE_BOUNDARIES.pop()
            boundary.close()


if __name__ == "__main__":
    run()
