"""Stable bootstrap candidate for Advanced Operations Onyx Live V20."""
from __future__ import annotations

import os
import platform
import runpy
import sys
from pathlib import Path


ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])).resolve()
LAUNCHER = ROOT / "scripts" / "launch_onyx_live_v20.pyw"


def _default_workspace_root() -> Path:
    from core.paths import data_root, private_control_plane_runtime_dir

    root = (
        data_root() / "workspace"
        if getattr(sys, "frozen", False)
        or os.environ.get("ONYX_DATA_DIR", "").strip()
        else private_control_plane_runtime_dir() / "workspace"
    )
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _run_v19(environment: dict[str, str] | os._Environ[str]) -> None:
    os.environ.clear()
    os.environ.update(environment)
    runpy.run_path(
        str(ROOT / "scripts" / "bootstrap_onyx_live_v19.pyw"),
        run_name="__main__",
    )


def _bootstrap_environment(
    environ: dict[str, str] | os._Environ[str],
) -> tuple[str, dict[str, str]]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from core import onyx_live_activation_v15 as v15
    from core import onyx_live_activation_v20 as v20

    if platform.system() != "Windows":
        return "v19", dict(environ)
    present = {
        name: environ[name]
        for name in (v20.LIVE_MASTER_FLAG, v20.LIVE_ROLLBACK_FLAG, v20.FEATURE_FLAG)
        if name in environ
    }
    if not present:
        if any(name in environ for name in v20.CONTROL_FLAGS[3:]):
            return "v19", dict(environ)
        return (
            "v20",
            {
                **dict(environ),
                **v20.exact_activation_environment(
                    (_default_workspace_root(),),
                    executable_docker_cli=v15.DEFAULT_WINDOWS_DOCKER_CLI,
                    executable_sandbox=Path(v15.DEFAULT_WINDOWS_DOCKER_CLI).is_file(),
                ),
            },
        )
    if present == {v20.LIVE_ROLLBACK_FLAG: "1"}:
        return "v19", v20.restore_v19_environment(environ)
    try:
        flags = v20.ActivationFlagsV20.from_canonical_environ(environ)
        base = flags.base.base.base.base.base
        canonical = v20.exact_activation_environment(
            base.workspace_roots,
            executable_docker_cli=base.executable_docker_cli,
            executable_docker_host=base.executable_docker_host,
            executable_platform=base.executable_platform,
            executable_image_ids=base.executable_image_ids,
            executable_sandbox=base.executable_sandbox,
        )
    except Exception as exc:
        raise RuntimeError("ONYX_LIVE_V20_PARTIAL_CONFIGURATION_REFUSED") from exc
    visible = {name: environ[name] for name in canonical if name in environ}
    if visible != canonical:
        raise RuntimeError("ONYX_LIVE_V20_PARTIAL_CONFIGURATION_REFUSED")
    return "v20", {**dict(environ), **canonical}


def run() -> None:
    accepted = (
        [],
        ["--preflight-only"],
        ["--governance-smoke-test"],
        ["--founder-smoke-test"],
        ["--document-intake-smoke-test"],
        ["--dayops-smoke-test"],
        ["--advanced-operations-smoke-test"],
        ["--native-startup-smoke-test"],
    )
    if sys.argv[1:] not in accepted:
        raise RuntimeError("Onyx Live V20 bootstrap arguments are invalid")
    if sys.argv[1:] in (
        ["--governance-smoke-test"],
        ["--founder-smoke-test"],
        ["--document-intake-smoke-test"],
    ):
        _run_v19(dict(os.environ))
        return
    mode, prepared = _bootstrap_environment(os.environ)
    if mode == "v19":
        _run_v19(prepared)
        return
    os.environ.clear()
    os.environ.update(prepared)
    os.chdir(ROOT)
    runpy.run_path(str(LAUNCHER), run_name="__main__")


if __name__ == "__main__":
    run()

