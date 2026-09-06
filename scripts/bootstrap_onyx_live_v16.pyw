"""Stable bootstrap for canonical Onyx Live V16 governance activation."""
from __future__ import annotations

import os
import platform
import runpy
import sys
from pathlib import Path


ROOT = Path(
    getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])
).resolve()
LAUNCHER = ROOT / "scripts" / "launch_onyx_live_v16.pyw"


def _default_workspace_root() -> Path:
    from core.paths import data_root, private_control_plane_runtime_dir

    if (
        getattr(sys, "frozen", False)
        or os.environ.get("ONYX_DATA_DIR", "").strip()
    ):
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
    from core import onyx_live_activation_v14 as v14
    from core import onyx_live_activation_v15 as v15
    from core import onyx_live_activation_v16 as v16

    present = {
        name: environ[name] for name in v16.CONTROL_FLAGS if name in environ
    }
    result = dict(environ)
    for name in v16.CONTROL_FLAGS:
        result.pop(name, None)
    if not present:
        if platform.system() == "Windows":
            result.update(
                v16.exact_activation_environment(
                    (_default_workspace_root(),),
                    executable_docker_cli=v15.DEFAULT_WINDOWS_DOCKER_CLI,
                    executable_sandbox=Path(
                        v15.DEFAULT_WINDOWS_DOCKER_CLI
                    ).is_file(),
                )
            )
        else:
            result.update(v14.exact_activation_environment())
        return result
    if present == {v16.LIVE_ROLLBACK_FLAG: "1"}:
        if platform.system() == "Windows" and not (
            v16._consume_host_downgrade_receipt_v1("rollback")
        ):
            raise RuntimeError(
                "ONYX_LIVE_V16_DOWNGRADE_RECEIPT_REQUIRED"
            )
        result.update(present)
        return result
    canonical_v14 = v14.exact_activation_environment()
    if present == canonical_v14:
        if platform.system() == "Windows" and not (
            v16._consume_host_downgrade_receipt_v1("v14")
        ):
            raise RuntimeError(
                "ONYX_LIVE_V16_DOWNGRADE_RECEIPT_REQUIRED"
            )
        result.update(canonical_v14)
        return result
    try:
        v15.ActivationFlagsV15.from_canonical_environ(environ)
    except Exception:
        pass
    else:
        if (
            v16.LIVE_MASTER_FLAG not in present
            and v16.FEATURE_FLAG not in present
        ):
            if platform.system() != "Windows":
                raise RuntimeError(v15.PLATFORM_REFUSAL_SIGNAL)
            if not v16._consume_host_downgrade_receipt_v1("v15"):
                raise RuntimeError(
                    "ONYX_LIVE_V16_DOWNGRADE_RECEIPT_REQUIRED"
                )
            result.update(present)
            return result
    try:
        flags = v16.ActivationFlagsV16.from_canonical_environ(environ)
        canonical_v16 = v16.exact_activation_environment(
            flags.base.workspace_roots,
            executable_docker_cli=flags.base.executable_docker_cli,
            executable_docker_host=flags.base.executable_docker_host,
            executable_platform=flags.base.executable_platform,
            executable_image_ids=flags.base.executable_image_ids,
            executable_sandbox=flags.base.executable_sandbox,
        )
    except Exception as exc:
        raise RuntimeError(
            "ONYX_LIVE_V16_PARTIAL_CONFIGURATION_REFUSED"
        ) from exc
    if present != canonical_v16:
        raise RuntimeError("ONYX_LIVE_V16_PARTIAL_CONFIGURATION_REFUSED")
    result.update(canonical_v16)
    return result


def run() -> None:
    if sys.argv[1:] not in (
        [],
        ["--preflight-only"],
        ["--governance-smoke-test"],
    ):
        raise RuntimeError("Onyx Live V16 bootstrap arguments are invalid")
    prepared = _bootstrap_environment(os.environ)
    os.environ.clear()
    os.environ.update(prepared)
    os.chdir(ROOT)
    runpy.run_path(str(LAUNCHER), run_name="__main__")


if __name__ == "__main__":
    run()
