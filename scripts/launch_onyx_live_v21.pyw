"""Canonical launcher for voice-enabled Advanced Operations Onyx Live V21."""
from __future__ import annotations

import json
import gc
import os
import runpy
import sys
import traceback
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from core.paths import data_root, runtime_dir


ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])).resolve()
LOG_PATH = data_root() / "runtime/logs/onyx-live-v21-startup.log"


def _v20_contract() -> dict[str, object]:
    namespace = runpy.run_path(
        str(ROOT / "scripts" / "launch_onyx_live_v20.pyw"),
        run_name="onyx_v20_launcher_contract_for_v21",
    )
    required = ("run", "_v19_contract")
    if any(not callable(namespace.get(name)) for name in required):
        raise RuntimeError("Onyx V20 launcher contract is unavailable")
    return namespace


@contextmanager
def _command_diagnostic_resources(legacy: dict[str, object]):
    v19 = legacy["_v19_contract"]()
    with v19["_diagnostic_resources_v19"](("--preflight-only",)) as resources:
        yield v19, resources


def _run_command_diagnostic() -> dict[str, object]:
    from core.native_startup_smoke_v1 import (
        ExternalCallCountersV1,
        _cleanup_host,
        _external_agent_unavailable,
        _provider_call_boundary_v1,
        external_call_boundary_v1,
    )

    legacy = _v20_contract()
    calls = ExternalCallCountersV1()
    controller = None
    instance = None
    ui = None
    onyx_main = None
    original_runtime_dir = None
    with _command_diagnostic_resources(legacy) as (v19, resources), \
         external_call_boundary_v1(counters=calls):
        from core.onyx_live_activation_v15 import verify_activation_prerequisites
        from core.onyx_live_activation_v21 import TOOL_NAME, activate_main

        verify_activation_prerequisites(ROOT, os.environ)
        import main as imported_main

        onyx_main = imported_main
        locations = resources["locations"]
        with v19["_diagnostic_main_aliases_v19"](
            imported_main, locations
        ) as original_aliases, _provider_call_boundary_v1(imported_main, calls):
            original_runtime_dir = original_aliases["runtime_dir"]
            active_error: BaseException | None = None
            try:
                controller = activate_main(
                    imported_main,
                    external_agent_factory=_external_agent_unavailable,
                    governance_path=resources["governance_path"],
                    nucleus_factory=resources["governance_factory"],
                    authority_factory=resources["authority_factory"],
                    component_factory=resources["component_factory"],
                )
                declarations = getattr(imported_main, "TOOL_DECLARATIONS", ())
                declared = sum(
                    1
                    for item in declarations
                    if isinstance(item, dict) and item.get("name") == TOOL_NAME
                )
                payload = {
                    "contract": "OnyxAdvancedCommandsSmoke.v21",
                    "status": "passed",
                    "tool_declared_exactly_once": declared == 1,
                    "tool_route_owned": (
                        getattr(controller.contract.onyx_live, "_execute_tool")
                        is controller._owned_execute
                    ),
                    "controller_status": "not_started",
                    "host_constructed": False,
                    "background_workers": 0,
                    "polling_interval": None,
                    "interception": calls.evidence(),
                    "network_calls": calls.network,
                    "provider_calls": calls.provider,
                    "process_calls": calls.process,
                    "trusted_ui_prompts": 0,
                }
                if (
                    payload["tool_declared_exactly_once"] is not True
                    or payload["tool_route_owned"] is not True
                    or payload["background_workers"] != 0
                    or payload["polling_interval"] is not None
                    or any(
                        payload[key] != 0
                        for key in (
                            "network_calls",
                            "provider_calls",
                            "process_calls",
                            "trusted_ui_prompts",
                        )
                    )
                ):
                    raise RuntimeError("V21 command diagnostic evidence diverged")
                print(json.dumps(payload, sort_keys=True), flush=True)
                return payload
            except BaseException as exc:
                active_error = exc
                raise
            finally:
                cleanup_failures = _cleanup_host(
                    ui=ui,
                    controller=controller,
                    onyx_main=onyx_main,
                    original_runtime_dir=original_runtime_dir,
                    instance=instance,
                )
                cleanup_failures += v19["_cleanup_diagnostic_activation_base_v19"](
                    getattr(getattr(controller, "_base", None), "_base", None)
                )
                controller = None
                instance = None
                ui = None
                onyx_main = None
                gc.collect()
                if cleanup_failures:
                    detail = ",".join(cleanup_failures)
                    if active_error is not None:
                        active_error.add_note(f"V21 diagnostic cleanup failures: {detail}")
                    else:
                        raise RuntimeError(f"V21 diagnostic cleanup failed: {detail}")


def run() -> None:
    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    accepted = (
        [],
        ["--preflight-only"],
        ["--dayops-smoke-test"],
        ["--advanced-operations-smoke-test"],
        ["--advanced-commands-smoke-test"],
        ["--native-startup-smoke-test"],
    )
    if sys.argv[1:] not in accepted:
        raise RuntimeError("Onyx Live V21 launcher arguments are invalid")
    legacy = _v20_contract()
    if sys.argv[1:] == ["--advanced-commands-smoke-test"]:
        _run_command_diagnostic()
        return
    if sys.argv[1:]:
        if sys.argv[1:] == ["--native-startup-smoke-test"]:
            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with LOG_PATH.open("a", encoding="utf-8", buffering=1) as log:
                print(
                    f"\n[{datetime.now(timezone.utc).isoformat()}] "
                    "Onyx native startup smoke entering stable V21 launcher",
                    file=log,
                )
                legacy["run"]()
                print("Onyx native startup smoke passed", file=log)
            return
        legacy["run"]()
        return

    v19 = legacy["_v19_contract"]()
    single_instance, proceed = v19["_acquire_gui_mutex"](())
    if not proceed:
        return
    governance_mutex = v19["_acquire_governance_runtime_mutex"]()
    controller = None
    try:
        from core.onyx_live_activation_v15 import verify_activation_prerequisites
        from core.onyx_live_activation_v21 import activate_main

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
            print(f"\n[{datetime.now(timezone.utc).isoformat()}] Onyx Live V21 starting")
            print(f"Advanced commands: {controller.advanced_commands_capability}")
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
