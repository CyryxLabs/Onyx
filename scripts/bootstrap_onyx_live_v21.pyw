"""Stable bootstrap candidate for voice-enabled Advanced Operations V21."""
from __future__ import annotations

import os
import platform
import runpy
import sys
from pathlib import Path


ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])).resolve()
LAUNCHER = ROOT / "scripts" / "launch_onyx_live_v21.pyw"


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


def _run_v20(environment: dict[str, str] | os._Environ[str]) -> None:
    os.environ.clear()
    os.environ.update(environment)
    runpy.run_path(
        str(ROOT / "scripts" / "bootstrap_onyx_live_v20.pyw"),
        run_name="__main__",
    )


def _bootstrap_environment(
    environ: dict[str, str] | os._Environ[str],
) -> tuple[str, dict[str, str]]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from core import onyx_live_activation_v15 as v15
    from core import onyx_live_activation_v19 as v19
    from core import onyx_live_activation_v20 as v20
    from core import onyx_live_activation_v21 as v21

    if platform.system() != "Windows":
        return "v20", dict(environ)
    present = {
        name: environ[name]
        for name in (v21.LIVE_MASTER_FLAG, v21.LIVE_ROLLBACK_FLAG, v21.FEATURE_FLAG)
        if name in environ
    }
    if not present:
        predecessor_visible = {
            name: environ[name]
            for name in v21.CONTROL_FLAGS[3:]
            if name in environ
        }
        v15_base = None
        recognized_incomplete_v19 = False
        if predecessor_visible:
            try:
                previous = v20.ActivationFlagsV20.from_canonical_environ(environ)
                v15_base = previous.base.base.base.base.base
            except v20.ActivationV20Error as v20_exc:
                try:
                    previous_v19 = v19.ActivationFlagsV19.from_canonical_environ(
                        environ
                    )
                    v15_base = previous_v19.base.base.base.base
                except v19.ActivationV19Error:
                    migratable = {
                        v15.WORKSPACE_ROOTS_FLAG,
                        "ONYX_PHASE11_LOCAL_PROJECT_AUDIT_V1",
                    }
                    minimal_predecessor = (
                        not set(predecessor_visible).difference(migratable)
                        and predecessor_visible.get(
                            "ONYX_PHASE11_LOCAL_PROJECT_AUDIT_V1"
                        )
                        in {None, "true"}
                    )
                    recognized_incomplete_v19 = (
                        predecessor_visible.get(v19.LIVE_MASTER_FLAG) == "1"
                        and predecessor_visible.get(v19.FEATURE_FLAG) == "true"
                    )
                    if not minimal_predecessor and not recognized_incomplete_v19:
                        raise RuntimeError(
                            "ONYX_LIVE_V21_PARTIAL_CONFIGURATION_REFUSED"
                        ) from v20_exc
        if v15_base is not None:
            roots = v15_base.workspace_roots
            v20_options = {
                "executable_docker_cli": v15_base.executable_docker_cli,
                "executable_docker_host": v15_base.executable_docker_host,
                "executable_platform": v15_base.executable_platform,
                "executable_image_ids": v15_base.executable_image_ids,
                "executable_sandbox": v15_base.executable_sandbox,
            }
        else:
            raw_roots = environ.get(v15.WORKSPACE_ROOTS_FLAG, "")
            try:
                roots = (
                    v15._workspace_roots(raw_roots)
                    if raw_roots.strip()
                    else (str(_default_workspace_root()),)
                )
            except v15.ActivationV15Error as exc:
                raise RuntimeError(
                    "ONYX_LIVE_V21_PARTIAL_CONFIGURATION_REFUSED"
                ) from exc
            executable_flags = (
                v15.PROJECT_AUTOPILOT_FLAG,
                v15.EXECUTABLE_SANDBOX_FLAG,
                v15.EXECUTABLE_DOCKER_CLI_FLAG,
                v15.EXECUTABLE_DOCKER_HOST_FLAG,
                v15.EXECUTABLE_PLATFORM_FLAG,
                v15.EXECUTABLE_IMAGE_IDS_FLAG,
            )
            visible_executable = {
                name: predecessor_visible[name]
                for name in executable_flags
                if name in predecessor_visible
            }
            if visible_executable:
                if (
                    not recognized_incomplete_v19
                    or set(visible_executable) != set(executable_flags)
                    or visible_executable[v15.PROJECT_AUTOPILOT_FLAG] != "true"
                    or visible_executable[v15.EXECUTABLE_SANDBOX_FLAG]
                    not in {"true", "false"}
                ):
                    raise RuntimeError(
                        "ONYX_LIVE_V21_PARTIAL_CONFIGURATION_REFUSED"
                    )
                v20_options = {
                    "executable_docker_cli": visible_executable[
                        v15.EXECUTABLE_DOCKER_CLI_FLAG
                    ],
                    "executable_docker_host": visible_executable[
                        v15.EXECUTABLE_DOCKER_HOST_FLAG
                    ],
                    "executable_platform": visible_executable[
                        v15.EXECUTABLE_PLATFORM_FLAG
                    ],
                    "executable_image_ids": tuple(
                        visible_executable[v15.EXECUTABLE_IMAGE_IDS_FLAG].split(",")
                    ),
                    "executable_sandbox": visible_executable[
                        v15.EXECUTABLE_SANDBOX_FLAG
                    ]
                    == "true",
                }
            else:
                v20_options = {
                    "executable_docker_cli": v15.DEFAULT_WINDOWS_DOCKER_CLI,
                    "executable_sandbox": Path(
                        v15.DEFAULT_WINDOWS_DOCKER_CLI
                    ).is_file(),
                }
        try:
            canonical = v21.exact_activation_environment(
                roots,
                **v20_options,
            )
        except Exception as exc:
            raise RuntimeError(
                "ONYX_LIVE_V21_PARTIAL_CONFIGURATION_REFUSED"
            ) from exc
        if any(
            canonical.get(name) != value
            for name, value in predecessor_visible.items()
        ):
            raise RuntimeError("ONYX_LIVE_V21_PARTIAL_CONFIGURATION_REFUSED")
        prepared = dict(environ)
        for name in v21.CONTROL_FLAGS:
            prepared.pop(name, None)
        return (
            "v21",
            {
                **prepared,
                **canonical,
            },
        )
    if present == {v21.LIVE_ROLLBACK_FLAG: "1"}:
        return "v20", v21.restore_v20_environment(environ)
    try:
        flags = v21.ActivationFlagsV21.from_canonical_environ(environ)
        base = flags.base.base.base.base.base.base
        canonical = v21.exact_activation_environment(
            base.workspace_roots,
            executable_docker_cli=base.executable_docker_cli,
            executable_docker_host=base.executable_docker_host,
            executable_platform=base.executable_platform,
            executable_image_ids=base.executable_image_ids,
            executable_sandbox=base.executable_sandbox,
        )
    except Exception as exc:
        raise RuntimeError("ONYX_LIVE_V21_PARTIAL_CONFIGURATION_REFUSED") from exc
    visible = {name: environ[name] for name in canonical if name in environ}
    if visible != canonical:
        raise RuntimeError("ONYX_LIVE_V21_PARTIAL_CONFIGURATION_REFUSED")
    return "v21", {**dict(environ), **canonical}


def run() -> None:
    accepted = (
        [],
        ["--preflight-only"],
        ["--governance-smoke-test"],
        ["--founder-smoke-test"],
        ["--document-intake-smoke-test"],
        ["--dayops-smoke-test"],
        ["--advanced-operations-smoke-test"],
        ["--advanced-commands-smoke-test"],
        ["--native-startup-smoke-test"],
    )
    if sys.argv[1:] not in accepted:
        raise RuntimeError("Onyx Live V21 bootstrap arguments are invalid")
    if sys.argv[1:] in (
        ["--governance-smoke-test"],
        ["--founder-smoke-test"],
        ["--document-intake-smoke-test"],
    ):
        mode, prepared = _bootstrap_environment(os.environ)
        if mode == "v21":
            from core import onyx_live_activation_v21 as v21

            prepared = v21.restore_v20_environment(prepared)
        _run_v20(prepared)
        return
    mode, prepared = _bootstrap_environment(os.environ)
    if mode == "v20":
        _run_v20(prepared)
        return
    os.environ.clear()
    os.environ.update(prepared)
    os.chdir(ROOT)
    runpy.run_path(str(LAUNCHER), run_name="__main__")


if __name__ == "__main__":
    run()
