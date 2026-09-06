"""Stable bootstrap for metadata-only operational events in Onyx Live V23."""
from __future__ import annotations

import os
import platform
import runpy
import sys
from pathlib import Path


ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])).resolve()
LAUNCHER = ROOT / "scripts" / "launch_onyx_live_v23.pyw"
V22_BOOTSTRAP = ROOT / "scripts" / "bootstrap_onyx_live_v22.pyw"


def _v22_contract() -> dict[str, object]:
    namespace = runpy.run_path(
        str(V22_BOOTSTRAP), run_name="onyx_v22_bootstrap_contract_for_v23"
    )
    if not callable(namespace.get("_bootstrap_environment")):
        raise RuntimeError("Onyx V22 bootstrap contract is unavailable")
    return namespace


def _run_v22(environment: dict[str, str] | os._Environ[str]) -> None:
    os.environ.clear()
    os.environ.update(environment)
    runpy.run_path(str(V22_BOOTSTRAP), run_name="__main__")


def _bootstrap_environment(
    environ: dict[str, str] | os._Environ[str],
) -> tuple[str, dict[str, str]]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from core import onyx_live_activation_v23 as v23

    if platform.system() != "Windows":
        return "v22", dict(environ)
    present = {
        name: environ[name]
        for name in (v23.LIVE_MASTER_FLAG, v23.LIVE_ROLLBACK_FLAG, v23.FEATURE_FLAG)
        if name in environ
    }
    if not present:
        mode, prepared = _v22_contract()["_bootstrap_environment"](environ)
        if mode != "v22":
            return "v22", prepared
        canonical = dict(prepared)
        canonical[v23.LIVE_MASTER_FLAG] = "1"
        canonical[v23.FEATURE_FLAG] = "true"
        try:
            v23.ActivationFlagsV23.from_canonical_environ(canonical)
        except Exception as exc:
            raise RuntimeError("ONYX_LIVE_V23_PARTIAL_CONFIGURATION_REFUSED") from exc
        return "v23", canonical
    if present == {v23.LIVE_ROLLBACK_FLAG: "1"}:
        return "v22", v23.restore_v22_environment(environ)
    try:
        flags = v23.ActivationFlagsV23.from_canonical_environ(environ)
        base = flags.base.base.base.base.base.base.base.base
        canonical = v23.exact_activation_environment(
            base.workspace_roots,
            executable_docker_cli=base.executable_docker_cli,
            executable_docker_host=base.executable_docker_host,
            executable_platform=base.executable_platform,
            executable_image_ids=base.executable_image_ids,
            executable_sandbox=base.executable_sandbox,
        )
    except Exception as exc:
        raise RuntimeError("ONYX_LIVE_V23_PARTIAL_CONFIGURATION_REFUSED") from exc
    visible = {name: environ[name] for name in canonical if name in environ}
    if visible != canonical:
        raise RuntimeError("ONYX_LIVE_V23_PARTIAL_CONFIGURATION_REFUSED")
    return "v23", {**dict(environ), **canonical}


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
        ["--owner-context-smoke-test"],
        ["--operational-events-smoke-test"],
        ["--native-startup-smoke-test"],
    )
    if sys.argv[1:] not in accepted:
        raise RuntimeError("Onyx Live V23 bootstrap arguments are invalid")
    mode, prepared = _bootstrap_environment(os.environ)
    if sys.argv[1:] not in (
        [],
        ["--operational-events-smoke-test"],
        ["--native-startup-smoke-test"],
    ):
        if mode == "v23":
            from core import onyx_live_activation_v23 as v23

            prepared = v23.restore_v22_environment(prepared)
        _run_v22(prepared)
        return
    if mode == "v22":
        _run_v22(prepared)
        return
    os.environ.clear()
    os.environ.update(prepared)
    os.chdir(ROOT)
    runpy.run_path(str(LAUNCHER), run_name="__main__")


if __name__ == "__main__":
    run()
