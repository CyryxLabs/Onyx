"""Stable bootstrap for canonical Onyx Live V17 Founder activation."""
from __future__ import annotations

import os
import platform
import runpy
import sys
from pathlib import Path


ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])).resolve()
LAUNCHER = ROOT / "scripts" / "launch_onyx_live_v17.pyw"


def _default_workspace_root() -> Path:
    from core.paths import data_root, private_control_plane_runtime_dir

    root = (
        data_root() / "workspace"
        if getattr(sys, "frozen", False) or os.environ.get("ONYX_DATA_DIR", "").strip()
        else private_control_plane_runtime_dir() / "workspace"
    )
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _run_v16(environment: dict[str, str] | os._Environ[str]) -> None:
    os.environ.clear()
    os.environ.update(environment)
    runpy.run_path(
        str(ROOT / "scripts" / "bootstrap_onyx_live_v16.pyw"),
        run_name="__main__",
    )


def _bootstrap_environment(
    environ: dict[str, str] | os._Environ[str],
) -> tuple[str, dict[str, str]]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from core import onyx_live_activation_v15 as v15
    from core import onyx_live_activation_v17 as v17

    if platform.system() != "Windows":
        return "v16", dict(environ)
    present_v17 = {
        name: environ[name]
        for name in (v17.LIVE_MASTER_FLAG, v17.LIVE_ROLLBACK_FLAG, v17.FEATURE_FLAG)
        if name in environ
    }
    if not present_v17:
        lower_present = {name for name in v17.CONTROL_FLAGS[3:] if name in environ}
        if lower_present:
            return "v16", dict(environ)
        return (
            "v17",
            {
                **dict(environ),
                **v17.exact_activation_environment(
                    (_default_workspace_root(),),
                    executable_docker_cli=v15.DEFAULT_WINDOWS_DOCKER_CLI,
                    executable_sandbox=Path(v15.DEFAULT_WINDOWS_DOCKER_CLI).is_file(),
                ),
            },
        )
    if present_v17 == {v17.LIVE_ROLLBACK_FLAG: "1"}:
        result = v17.restore_v16_environment(environ)
        return "v16", result
    try:
        flags = v17.ActivationFlagsV17.from_canonical_environ(environ)
        canonical = v17.exact_activation_environment(
            flags.base.base.workspace_roots,
            executable_docker_cli=flags.base.base.executable_docker_cli,
            executable_docker_host=flags.base.base.executable_docker_host,
            executable_platform=flags.base.base.executable_platform,
            executable_image_ids=flags.base.base.executable_image_ids,
            executable_sandbox=flags.base.base.executable_sandbox,
        )
    except Exception as exc:
        raise RuntimeError("ONYX_LIVE_V17_PARTIAL_CONFIGURATION_REFUSED") from exc
    visible = {name: environ[name] for name in canonical if name in environ}
    if visible != canonical:
        raise RuntimeError("ONYX_LIVE_V17_PARTIAL_CONFIGURATION_REFUSED")
    return "v17", {**dict(environ), **canonical}


def run() -> None:
    if sys.argv[1:] not in (
        [],
        ["--preflight-only"],
        ["--governance-smoke-test"],
        ["--founder-smoke-test"],
    ):
        raise RuntimeError("Onyx Live V17 bootstrap arguments are invalid")
    mode, prepared = _bootstrap_environment(os.environ)
    if mode == "v16":
        _run_v16(prepared)
        return
    os.environ.clear()
    os.environ.update(prepared)
    os.chdir(ROOT)
    runpy.run_path(str(LAUNCHER), run_name="__main__")


if __name__ == "__main__":
    run()
