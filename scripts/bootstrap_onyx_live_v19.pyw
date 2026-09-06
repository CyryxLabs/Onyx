"""Stable bootstrap for persistent DayOps Onyx Live V19."""
from __future__ import annotations

import os
import platform
import runpy
import sys
from pathlib import Path


ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])).resolve()
LAUNCHER = ROOT / "scripts" / "launch_onyx_live_v19.pyw"


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


def _run_v18(environment: dict[str, str] | os._Environ[str]) -> None:
    os.environ.clear()
    os.environ.update(environment)
    runpy.run_path(
        str(ROOT / "scripts" / "bootstrap_onyx_live_v18.pyw"),
        run_name="__main__",
    )


def _bootstrap_environment(
    environ: dict[str, str] | os._Environ[str],
) -> tuple[str, dict[str, str]]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from core import onyx_live_activation_v15 as v15
    from core import onyx_live_activation_v19 as v19

    if platform.system() != "Windows":
        return "v18", dict(environ)
    present = {
        name: environ[name]
        for name in (
            v19.LIVE_MASTER_FLAG,
            v19.LIVE_ROLLBACK_FLAG,
            v19.FEATURE_FLAG,
        )
        if name in environ
    }
    if not present:
        if any(name in environ for name in v19.CONTROL_FLAGS[3:]):
            return "v18", dict(environ)
        return (
            "v19",
            {
                **dict(environ),
                **v19.exact_activation_environment(
                    (_default_workspace_root(),),
                    executable_docker_cli=v15.DEFAULT_WINDOWS_DOCKER_CLI,
                    executable_sandbox=Path(
                        v15.DEFAULT_WINDOWS_DOCKER_CLI
                    ).is_file(),
                ),
            },
        )
    if present == {v19.LIVE_ROLLBACK_FLAG: "1"}:
        return "v18", v19.restore_v18_environment(environ)
    try:
        flags = v19.ActivationFlagsV19.from_canonical_environ(environ)
        base = flags.base.base.base.base
        canonical = v19.exact_activation_environment(
            base.workspace_roots,
            executable_docker_cli=base.executable_docker_cli,
            executable_docker_host=base.executable_docker_host,
            executable_platform=base.executable_platform,
            executable_image_ids=base.executable_image_ids,
            executable_sandbox=base.executable_sandbox,
        )
    except Exception as exc:
        raise RuntimeError("ONYX_LIVE_V19_PARTIAL_CONFIGURATION_REFUSED") from exc
    visible = {name: environ[name] for name in canonical if name in environ}
    if visible != canonical:
        raise RuntimeError("ONYX_LIVE_V19_PARTIAL_CONFIGURATION_REFUSED")
    return "v19", {**dict(environ), **canonical}


def run() -> None:
    accepted = (
        [],
        ["--preflight-only"],
        ["--governance-smoke-test"],
        ["--founder-smoke-test"],
        ["--document-intake-smoke-test"],
        ["--dayops-smoke-test"],
        ["--native-startup-smoke-test"],
    )
    if sys.argv[1:] not in accepted:
        raise RuntimeError("Onyx Live V19 bootstrap arguments are invalid")
    if sys.argv[1:] in (
        ["--governance-smoke-test"],
        ["--founder-smoke-test"],
        ["--document-intake-smoke-test"],
    ):
        _run_v18(dict(os.environ))
        return
    if sys.argv[1:] == ["--native-startup-smoke-test"]:
        # The bounded native smoke owns its exact activation environment. Keep
        # the real stable -> V19 bootstrap -> V19 launcher chain on every host
        # instead of falling through a lower-version platform bootstrap.
        os.chdir(ROOT)
        runpy.run_path(str(LAUNCHER), run_name="__main__")
        return
    mode, prepared = _bootstrap_environment(os.environ)
    if mode == "v18":
        _run_v18(prepared)
        return
    os.environ.clear()
    os.environ.update(prepared)
    os.chdir(ROOT)
    runpy.run_path(str(LAUNCHER), run_name="__main__")


if __name__ == "__main__":
    run()
