"""Desktop bootstrap establishing the exact canonical V12 environment."""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts/launch_onyx_live_v12.pyw"


def _bootstrap_environment(
    environ: dict[str, str] | os._Environ[str],
) -> dict[str, str]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from core.onyx_live_activation_v12 import CONTROL_FLAGS
    from core.onyx_live_activation_v12 import exact_activation_environment

    result = dict(environ)
    for name in CONTROL_FLAGS:
        result.pop(name, None)
    result.update(exact_activation_environment())
    return result


def run() -> None:
    if sys.argv[1:] not in ([], ["--preflight-only"]):
        raise RuntimeError("Onyx Live V12 bootstrap arguments are invalid")
    prepared = _bootstrap_environment(os.environ)
    os.environ.clear()
    os.environ.update(prepared)
    os.chdir(ROOT)
    runpy.run_path(str(LAUNCHER), run_name="__main__")


if __name__ == "__main__":
    run()
