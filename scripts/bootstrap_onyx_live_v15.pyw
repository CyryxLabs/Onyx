"""Stable bootstrap for canonical Onyx Live V15.

Windows desktop launches activate V15 against a private Onyx workspace when
the owner has not provisioned explicit workspace roots yet.  Other platforms
retain the V14 fallback until the V15 Windows-only Phase 11 host is replaced.
"""
from __future__ import annotations

import os
import platform
import runpy
import sys
from pathlib import Path


ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])).resolve()
LAUNCHER = ROOT / "scripts" / "launch_onyx_live_v15.pyw"


def _default_workspace_root() -> Path:
    from core.paths import data_root, private_control_plane_runtime_dir

    if getattr(sys, "frozen", False) or os.environ.get("ONYX_DATA_DIR", "").strip():
        root = data_root() / "workspace"
    else:
        root = private_control_plane_runtime_dir() / "workspace"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _bootstrap_environment(
    environ: dict[str, str] | os._Environ[str],
) -> dict[str, str]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from core.onyx_live_activation_v15 import (
        CONTROL_FLAGS,
        DEFAULT_WINDOWS_DOCKER_CLI,
        EXECUTABLE_DOCKER_CLI_FLAG,
        EXECUTABLE_DOCKER_HOST_FLAG,
        EXECUTABLE_IMAGE_IDS_FLAG,
        EXECUTABLE_PLATFORM_FLAG,
        LIVE_MASTER_FLAG,
        LIVE_ROLLBACK_FLAG,
        exact_activation_environment,
    )
    from core.phase11_executable_sandbox_v1 import (
        FEATURE_FLAG as executable_sandbox_flag,
    )
    from core.phase11_live_mission_v1 import FEATURE_FLAG, WORKSPACE_ROOTS_FLAG
    from core.phase11_project_autopilot_v1 import (
        FEATURE_FLAG as project_autopilot_flag,
    )
    from core.onyx_live_activation_v14 import exact_activation_environment as v14_environment

    requested = environ.get(FEATURE_FLAG)
    roots = environ.get(WORKSPACE_ROOTS_FLAG)
    executable = {
        project_autopilot_flag: environ.get(project_autopilot_flag),
        executable_sandbox_flag: environ.get(executable_sandbox_flag),
        EXECUTABLE_DOCKER_CLI_FLAG: environ.get(
            EXECUTABLE_DOCKER_CLI_FLAG
        ),
        EXECUTABLE_DOCKER_HOST_FLAG: environ.get(
            EXECUTABLE_DOCKER_HOST_FLAG
        ),
        EXECUTABLE_PLATFORM_FLAG: environ.get(EXECUTABLE_PLATFORM_FLAG),
        EXECUTABLE_IMAGE_IDS_FLAG: environ.get(EXECUTABLE_IMAGE_IDS_FLAG),
    }
    present = {
        name: environ[name] for name in CONTROL_FLAGS if name in environ
    }
    result = dict(environ)
    for name in CONTROL_FLAGS:
        result.pop(name, None)
    if not present:
        if platform.system() == "Windows":
            result.update(
                exact_activation_environment(
                    (_default_workspace_root(),),
                    executable_docker_cli=DEFAULT_WINDOWS_DOCKER_CLI,
                    executable_sandbox=Path(
                        DEFAULT_WINDOWS_DOCKER_CLI
                    ).is_file(),
                )
            )
        else:
            result.update(v14_environment())
        return result
    if present == {LIVE_ROLLBACK_FLAG: "1"}:
        result[LIVE_ROLLBACK_FLAG] = "1"
        return result
    canonical_v14 = v14_environment()
    if present == canonical_v14:
        result.update(canonical_v14)
        return result
    if (
        environ.get(LIVE_MASTER_FLAG) != "1"
        or environ.get(LIVE_ROLLBACK_FLAG) is not None
        or requested != "true"
        or not roots
        or executable[project_autopilot_flag] != "true"
        or executable[executable_sandbox_flag] not in {"true", "false"}
        or any(
            executable[name] is None
            for name in (
                EXECUTABLE_DOCKER_CLI_FLAG,
                EXECUTABLE_DOCKER_HOST_FLAG,
                EXECUTABLE_PLATFORM_FLAG,
                EXECUTABLE_IMAGE_IDS_FLAG,
            )
        )
    ):
        raise RuntimeError("ONYX_LIVE_V15_PARTIAL_CONFIGURATION_REFUSED")
    canonical_v15 = exact_activation_environment(
        roots.split(os.pathsep),
        executable_docker_cli=str(
            executable[EXECUTABLE_DOCKER_CLI_FLAG]
        ),
        executable_docker_host=str(
            executable[EXECUTABLE_DOCKER_HOST_FLAG]
        ),
        executable_platform=str(executable[EXECUTABLE_PLATFORM_FLAG]),
        executable_image_ids=str(
            executable[EXECUTABLE_IMAGE_IDS_FLAG]
        ).split(","),
        executable_sandbox=(
            executable[executable_sandbox_flag] == "true"
        ),
    )
    if present != canonical_v15:
        raise RuntimeError("ONYX_LIVE_V15_PARTIAL_CONFIGURATION_REFUSED")
    result.update(canonical_v15)
    return result


def run() -> None:
    if sys.argv[1:] not in ([], ["--preflight-only"]):
        raise RuntimeError("Onyx Live V15 bootstrap arguments are invalid")
    prepared = _bootstrap_environment(os.environ)
    os.environ.clear()
    os.environ.update(prepared)
    os.chdir(ROOT)
    runpy.run_path(str(LAUNCHER), run_name="__main__")


if __name__ == "__main__":
    run()
