"""Stable bootstrap for the final shutdown-dispatch guard in Onyx Live V24."""
from __future__ import annotations

import os
import platform
import runpy
import sys
from pathlib import Path


ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])).resolve()
LAUNCHER = ROOT / "scripts" / "launch_onyx_live_v24.pyw"
V23_BOOTSTRAP = ROOT / "scripts" / "bootstrap_onyx_live_v23.pyw"


def _normalize_windows_empty_launch_arguments() -> None:
    """Normalize only the two Windows forms of an omitted desktop argument."""

    if platform.system() != "Windows" or sys.argv[1:] not in ([""], ['""']):
        return
    sys.argv[:] = [sys.argv[0]]


def _v23_contract() -> dict[str, object]:
    namespace = runpy.run_path(
        str(V23_BOOTSTRAP), run_name="onyx_v23_bootstrap_contract_for_v24"
    )
    if not callable(namespace.get("_bootstrap_environment")):
        raise RuntimeError("Onyx V23 bootstrap contract is unavailable")
    return namespace


def _run_v23(environment: dict[str, str] | os._Environ[str]) -> None:
    os.environ.clear()
    os.environ.update(environment)
    runpy.run_path(str(V23_BOOTSTRAP), run_name="__main__")


def _bootstrap_environment(
    environ: dict[str, str] | os._Environ[str],
) -> tuple[str, dict[str, str]]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from core import onyx_live_activation_v24 as v24

    if platform.system() != "Windows":
        return "v23", dict(environ)
    present = {
        name: environ[name]
        for name in (v24.LIVE_MASTER_FLAG, v24.LIVE_ROLLBACK_FLAG, v24.FEATURE_FLAG)
        if name in environ
    }
    if not present:
        mode, prepared = _v23_contract()["_bootstrap_environment"](environ)
        if mode != "v23":
            return "v23", prepared
        canonical = dict(prepared)
        canonical[v24.LIVE_MASTER_FLAG] = "1"
        canonical[v24.FEATURE_FLAG] = "true"
        v24.ActivationFlagsV24.from_canonical_environ(canonical)
        return "v24", canonical
    if present == {v24.LIVE_ROLLBACK_FLAG: "1"}:
        return "v23", v24.restore_v23_environment(environ)
    try:
        v24.ActivationFlagsV24.from_canonical_environ(environ)
    except Exception as exc:
        raise RuntimeError("ONYX_LIVE_V24_PARTIAL_CONFIGURATION_REFUSED") from exc
    if present != {v24.LIVE_MASTER_FLAG: "1", v24.FEATURE_FLAG: "true"}:
        raise RuntimeError("ONYX_LIVE_V24_PARTIAL_CONFIGURATION_REFUSED")
    return "v24", dict(environ)


def run() -> None:
    _normalize_windows_empty_launch_arguments()
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
        raise RuntimeError("Onyx Live V24 bootstrap arguments are invalid")
    mode, prepared = _bootstrap_environment(os.environ)
    if sys.argv[1:] not in ([], ["--native-startup-smoke-test"]):
        if mode == "v24":
            from core import onyx_live_activation_v24 as v24

            prepared = v24.restore_v23_environment(prepared)
        _run_v23(prepared)
        return
    if mode == "v23":
        _run_v23(prepared)
        return
    os.environ.clear()
    os.environ.update(prepared)
    os.chdir(ROOT)
    runpy.run_path(str(LAUNCHER), run_name="__main__")


if __name__ == "__main__":
    run()
