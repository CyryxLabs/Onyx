"""Canonical pre-import launcher for Onyx Live Activation V18."""
from __future__ import annotations

import os
import runpy
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

from core.paths import data_root, runtime_dir


ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])).resolve()
LOG_PATH = data_root() / "runtime/logs/onyx-live-v18-startup.log"


def _windows_single_instance_factory_v18() -> object:
    """Reuse the accepted V17 GUI mutex contract and stable mutex name."""

    namespace = runpy.run_path(
        str(ROOT / "scripts" / "launch_onyx_live_v17.pyw"),
        run_name="onyx_v17_single_instance_contract",
    )
    mutex_type = namespace.get("_WindowsSingleInstanceV17")
    if not isinstance(mutex_type, type):
        raise RuntimeError("Onyx V17 single-instance contract is unavailable")
    return mutex_type()


def _acquire_gui_mutex_for_mode_v18(
    arguments: tuple[str, ...],
    *,
    factory=None,
) -> tuple[object | None, bool]:
    """Acquire only for a normal GUI launch; diagnostics remain independent."""

    if arguments:
        return None, True
    selected_factory = factory or _windows_single_instance_factory_v18
    single_instance = selected_factory()
    try:
        acquired = single_instance.acquire()
    except BaseException:
        single_instance.close()
        raise
    if not acquired:
        single_instance.close()
        return None, False
    return single_instance, True


def _run_v17() -> None:
    from core.onyx_live_activation_v18 import restore_v17_environment

    restored = restore_v17_environment(os.environ)
    os.environ.clear()
    os.environ.update(restored)
    runpy.run_path(
        str(ROOT / "scripts" / "launch_onyx_live_v17.pyw"),
        run_name="__main__",
    )


class _PreflightUI:
    def __init__(self) -> None:
        self.muted = True
        self.current_file = None

    def write_log(self, _value: str) -> None:
        pass

    def set_state(self, _value: str) -> None:
        pass


def run() -> None:
    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    if sys.argv[1:] in (["--governance-smoke-test"], ["--founder-smoke-test"]):
        _run_v17()
        return
    if sys.argv[1:] not in (
        [],
        ["--preflight-only"],
        ["--document-intake-smoke-test"],
    ):
        raise RuntimeError("Onyx Live V18 launcher arguments are invalid")
    single_instance, proceed = _acquire_gui_mutex_for_mode_v18(
        tuple(sys.argv[1:])
    )
    if not proceed:
        return
    controller = None
    try:
        from core.dayops_graph_factory_v1 import (
            create_canonical_dayops_graph_factory_v1,
        )
        from core.onyx_live_activation_v15 import verify_activation_prerequisites
        from core.onyx_live_activation_v18 import (
            DOCUMENT_INTAKE_SMOKE_FAILURE_EXIT,
            DocumentIntakeSmokePlatformRefusalV181,
            activate_main,
            run_document_intake_smoke_v181,
            write_document_intake_smoke_failure_v181,
        )

        verify_activation_prerequisites(ROOT, os.environ)
        phase11_runtime = runtime_dir() / "phase11-authority-v1"
        phase11_runtime.mkdir(parents=True, exist_ok=True)
        import main as onyx_main

        onyx_main.runtime_dir = lambda: phase11_runtime.resolve()
        dayops_factory = create_canonical_dayops_graph_factory_v1(
            environ=os.environ, project_root=ROOT
        )
        if sys.argv[1:] == ["--document-intake-smoke-test"]:
            try:
                run_document_intake_smoke_v181(
                    onyx_main,
                    dayops_factory=dayops_factory,
                )
            except DocumentIntakeSmokePlatformRefusalV181:
                from core.onyx_live_activation_v15 import PLATFORM_REFUSAL_EXIT

                if getattr(sys, "frozen", False) or getattr(sys, "_MEIPASS", None):
                    os._exit(PLATFORM_REFUSAL_EXIT)
                raise
            except BaseException as exc:
                write_document_intake_smoke_failure_v181(exc)
                if getattr(sys, "frozen", False) or getattr(sys, "_MEIPASS", None):
                    os._exit(DOCUMENT_INTAKE_SMOKE_FAILURE_EXIT)
                raise
            if getattr(sys, "frozen", False) or getattr(sys, "_MEIPASS", None):
                os._exit(0)
            return
        controller = activate_main(
            onyx_main,
            dayops_factory=dayops_factory,
        )
        if sys.argv[1:] == ["--preflight-only"]:
            controller.instantiate_live(_PreflightUI())
            print(
                "ONYX_LIVE_V18_HOST_PREFLIGHT_OK "
                "document_intake=provider-free governance=v16-authority "
                "founder=v17 network_calls=0 provider_calls=0 process_calls=0"
            )
            return
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8", buffering=1) as log:
            sys.stdout = log
            sys.stderr = log
            print(
                f"\n[{datetime.now(timezone.utc).isoformat()}] "
                "Onyx Live V18 starting"
            )
            try:
                print(
                    "Document Intake capability: "
                    f"{controller.document_intake_capability}"
                )
                onyx_main.main()
            except BaseException:
                traceback.print_exc()
                raise
    finally:
        try:
            if controller is not None:
                controller.rollback_to_v17()
        finally:
            if single_instance is not None:
                single_instance.close()


if __name__ == "__main__":
    run()
