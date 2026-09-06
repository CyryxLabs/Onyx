"""Canonical launcher for the final outer dispatch guard in Onyx Live V24."""
from __future__ import annotations

import os
import runpy
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

from core.paths import runtime_dir


ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])).resolve()
LOG_PATH = runtime_dir() / "logs/onyx-live-v24-startup.log"


def _v23_contract() -> dict[str, object]:
    namespace = runpy.run_path(
        str(ROOT / "scripts" / "launch_onyx_live_v23.pyw"),
        run_name="onyx_v23_launcher_contract_for_v24",
    )
    if not callable(namespace.get("run")) or not callable(namespace.get("_v22_contract")):
        raise RuntimeError("Onyx V23 launcher contract is unavailable")
    return namespace


def run() -> None:
    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    accepted = ([], ["--native-startup-smoke-test"])
    if sys.argv[1:] not in accepted:
        raise RuntimeError("Onyx Live V24 launcher arguments are invalid")
    legacy = _v23_contract()
    if sys.argv[1:] == ["--native-startup-smoke-test"]:
        # V20 owns the terminal frozen-process exit for this diagnostic, so
        # outer launchers never regain control after delegation.  Persist and
        # close the V24 entry evidence first; the release gate can then prove
        # the exact outer boundary without relying on a post-return marker or
        # on interpreter shutdown flushing buffered data.
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8", buffering=1) as log:
            print(
                f"\n[{datetime.now(timezone.utc).isoformat()}] "
                "Onyx native startup smoke entering stable V24 launcher",
                file=log,
                flush=True,
            )
        legacy["run"]()
        return

    v22 = legacy["_v22_contract"]()
    v21 = v22["_v21_contract"]()
    v20 = v21["_v20_contract"]()
    v19 = v20["_v19_contract"]()
    single_instance, proceed = v19["_acquire_gui_mutex"](())
    if not proceed:
        return
    governance_mutex = v19["_acquire_governance_runtime_mutex"]()
    controller = None
    try:
        from core.onyx_live_activation_v15 import verify_activation_prerequisites
        from core.onyx_live_activation_v24 import activate_main

        verify_activation_prerequisites(ROOT, os.environ)
        phase11_runtime = runtime_dir() / "phase11-authority-v1"
        phase11_runtime.mkdir(parents=True, exist_ok=True)
        import main as onyx_main

        onyx_main.runtime_dir = lambda: phase11_runtime.resolve()
        controller = activate_main(onyx_main)
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8", buffering=1) as log:
            sys.stdout = log
            sys.stderr = log
            print(f"\n[{datetime.now(timezone.utc).isoformat()}] Onyx Live V24 starting")
            try:
                onyx_main.main()
            except BaseException:
                traceback.print_exc()
                raise
    finally:
        try:
            if controller is not None:
                controller.rollback_all()
        finally:
            try:
                if governance_mutex is not None:
                    governance_mutex.release()
            finally:
                if single_instance is not None:
                    single_instance.close()


if __name__ == "__main__":
    run()
