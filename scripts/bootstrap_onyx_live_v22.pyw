"""Stable bootstrap for explicit owner-context Onyx Live V22."""
from __future__ import annotations

import os
import platform
import runpy
import sys
from pathlib import Path


ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])).resolve()
LAUNCHER = ROOT / "scripts" / "launch_onyx_live_v22.pyw"
V21_BOOTSTRAP = ROOT / "scripts" / "bootstrap_onyx_live_v21.pyw"


def _v21_contract() -> dict[str, object]:
    namespace = runpy.run_path(
        str(V21_BOOTSTRAP), run_name="onyx_v21_bootstrap_contract_for_v22"
    )
    if not callable(namespace.get("_bootstrap_environment")):
        raise RuntimeError("Onyx V21 bootstrap contract is unavailable")
    return namespace


def _run_v21(environment: dict[str, str] | os._Environ[str]) -> None:
    os.environ.clear()
    os.environ.update(environment)
    runpy.run_path(str(V21_BOOTSTRAP), run_name="__main__")


def _bootstrap_environment(
    environ: dict[str, str] | os._Environ[str],
) -> tuple[str, dict[str, str]]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from core import onyx_live_activation_v22 as v22

    if platform.system() != "Windows":
        return "v21", dict(environ)
    present = {
        name: environ[name]
        for name in (v22.LIVE_MASTER_FLAG, v22.LIVE_ROLLBACK_FLAG, v22.FEATURE_FLAG)
        if name in environ
    }
    if not present:
        mode, prepared = _v21_contract()["_bootstrap_environment"](environ)
        if mode != "v21":
            return "v21", prepared
        canonical = dict(prepared)
        canonical[v22.LIVE_MASTER_FLAG] = "1"
        canonical[v22.FEATURE_FLAG] = "true"
        try:
            v22.ActivationFlagsV22.from_canonical_environ(canonical)
        except Exception as exc:
            raise RuntimeError("ONYX_LIVE_V22_PARTIAL_CONFIGURATION_REFUSED") from exc
        return "v22", canonical
    if present == {v22.LIVE_ROLLBACK_FLAG: "1"}:
        return "v21", v22.restore_v21_environment(environ)
    try:
        flags = v22.ActivationFlagsV22.from_canonical_environ(environ)
        base = flags.base.base.base.base.base.base.base
        canonical = v22.exact_activation_environment(
            base.workspace_roots,
            executable_docker_cli=base.executable_docker_cli,
            executable_docker_host=base.executable_docker_host,
            executable_platform=base.executable_platform,
            executable_image_ids=base.executable_image_ids,
            executable_sandbox=base.executable_sandbox,
        )
    except Exception as exc:
        raise RuntimeError("ONYX_LIVE_V22_PARTIAL_CONFIGURATION_REFUSED") from exc
    visible = {name: environ[name] for name in canonical if name in environ}
    if visible != canonical:
        raise RuntimeError("ONYX_LIVE_V22_PARTIAL_CONFIGURATION_REFUSED")
    return "v22", {**dict(environ), **canonical}


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
        ["--native-startup-smoke-test"],
    )
    if sys.argv[1:] not in accepted:
        raise RuntimeError("Onyx Live V22 bootstrap arguments are invalid")
    mode, prepared = _bootstrap_environment(os.environ)
    if sys.argv[1:] not in (
        [],
        ["--owner-context-smoke-test"],
        ["--native-startup-smoke-test"],
    ):
        if mode == "v22":
            from core import onyx_live_activation_v22 as v22

            prepared = v22.restore_v21_environment(prepared)
        _run_v21(prepared)
        return
    if mode == "v21":
        _run_v21(prepared)
        return
    os.environ.clear()
    os.environ.update(prepared)
    os.chdir(ROOT)
    runpy.run_path(str(LAUNCHER), run_name="__main__")


if __name__ == "__main__":
    run()
