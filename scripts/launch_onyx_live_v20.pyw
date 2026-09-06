"""Canonical pre-import launcher for Advanced Operations Onyx Live V20."""
from __future__ import annotations

import json
import os
import runpy
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

from core.paths import data_root, runtime_dir


ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])).resolve()
LOG_PATH = data_root() / "runtime/logs/onyx-live-v20-startup.log"


def _v19_contract() -> dict[str, object]:
    namespace = runpy.run_path(
        str(ROOT / "scripts" / "launch_onyx_live_v19.pyw"),
        run_name="onyx_v19_launcher_contract_for_v20",
    )
    required = (
        "_acquire_gui_mutex",
        "_BoundedNativeSmokeMutexV19",
        "_run_native_startup_diagnostic",
        "_acquire_governance_runtime_mutex",
        "_diagnostic_resources_v19",
        "_PreflightUI",
        "_diagnostic_main_aliases_v19",
        "_cleanup_diagnostic_activation_base_v19",
    )
    if any(not callable(namespace.get(name)) for name in required):
        raise RuntimeError("Onyx V19 launcher contract is unavailable")
    return namespace


def _run_bounded_diagnostic(arguments: tuple[str, ...]) -> None:
    from core.native_startup_smoke_v1 import (
        ExternalCallCountersV1,
        INTERCEPTION_SCOPE,
        _cleanup_host,
        _external_agent_unavailable,
        _provider_call_boundary_v1,
        external_call_boundary_v1,
    )

    legacy = _v19_contract()
    resources_arguments = (
        ("--preflight-only",)
        if arguments == ("--advanced-operations-smoke-test",)
        else arguments
    )
    calls = ExternalCallCountersV1()
    controller = None
    instance = None
    ui = None
    onyx_main = None
    original_runtime_dir = None
    with legacy["_diagnostic_resources_v19"](
        resources_arguments
    ) as resources, external_call_boundary_v1(counters=calls):
        from core.onyx_live_activation_v15 import verify_activation_prerequisites
        from core.onyx_live_activation_v20 import activate_main

        verify_activation_prerequisites(ROOT, os.environ)
        import main as imported_main

        onyx_main = imported_main
        locations = resources["locations"]
        with legacy["_diagnostic_main_aliases_v19"](
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
                ui = legacy["_PreflightUI"]()
                instance = controller.instantiate_live(ui)
                advanced = getattr(instance, "_advanced_operations_controller_v1")
                advanced_status = advanced.status()
                if arguments == ("--advanced-operations-smoke-test",):
                    payload = {
                        "contract": "OnyxAdvancedOperationsSmoke.v20",
                        "status": "passed",
                        "controller_status": advanced_status.get("status"),
                        "callbacks_bound": all(
                            callable(getattr(ui, name, None))
                            for name in ("on_advanced_status", "on_advanced_attention")
                        ),
                        "background_workers": advanced_status.get("background_workers"),
                        "polling_interval": advanced_status.get("polling_interval"),
                        "interception": calls.evidence(),
                        "network_calls": calls.network,
                        "provider_calls": calls.provider,
                        "process_calls": calls.process,
                        "trusted_ui_prompts": ui.trusted_ui_prompts,
                    }
                    required = {
                        "contract": "OnyxAdvancedOperationsSmoke.v20",
                        "status": "passed",
                        "controller_status": "waiting_for_live_session",
                        "callbacks_bound": True,
                        "background_workers": 0,
                        "polling_interval": None,
                        "interception": calls.evidence(),
                        "network_calls": 0,
                        "provider_calls": 0,
                        "process_calls": 0,
                        "trusted_ui_prompts": 0,
                    }
                    if payload != required:
                        raise RuntimeError("Advanced Operations V20 smoke failed")
                    print(json.dumps(payload, sort_keys=True), flush=True)
                elif arguments == ("--dayops-smoke-test",):
                    dayops = getattr(instance, "_dayops_connection_controller_v19").status()
                    payload = {
                        "contract": "OnyxDayOpsSmoke.v20",
                        "status": "passed",
                        "connection_status": dayops.get("status"),
                        "read_only": dayops.get("read_only"),
                        "callbacks_bound": all(
                            callable(getattr(ui, name, None))
                            for name in (
                                "on_dayops_status",
                                "on_dayops_connect",
                                "on_dayops_sign_in",
                                "on_dayops_disconnect",
                                "on_dayops_today_brief",
                            )
                        ),
                        "advanced_callbacks_bound": all(
                            callable(getattr(ui, name, None))
                            for name in ("on_advanced_status", "on_advanced_attention")
                        ),
                        "advanced_controller_status": advanced_status.get("status"),
                        "interception": calls.evidence(),
                        "network_calls": calls.network,
                        "provider_calls": calls.provider,
                        "process_calls": calls.process,
                        "trusted_ui_prompts": ui.trusted_ui_prompts,
                    }
                    if payload != {
                        "contract": "OnyxDayOpsSmoke.v20",
                        "status": "passed",
                        "connection_status": "configuration_required",
                        "read_only": True,
                        "callbacks_bound": True,
                        "advanced_callbacks_bound": True,
                        "advanced_controller_status": "waiting_for_live_session",
                        "interception": calls.evidence(),
                        "network_calls": 0,
                        "provider_calls": 0,
                        "process_calls": 0,
                        "trusted_ui_prompts": 0,
                    }:
                        raise RuntimeError("DayOps V20 disconnected smoke failed")
                    print(json.dumps(payload, sort_keys=True), flush=True)
                else:
                    print(
                        "ONYX_LIVE_V20_HOST_PREFLIGHT_OK "
                        "base=v19-exact advanced_operations=lazy-zero-polling "
                        "phase6=single-core mission_store=single-authority "
                        f"network_calls={calls.network} provider_calls={calls.provider} "
                        f"process_calls={calls.process} interception_scope={INTERCEPTION_SCOPE}",
                        flush=True,
                    )
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
                cleanup_failures += legacy["_cleanup_diagnostic_activation_base_v19"](
                    getattr(controller, "_base", None)
                )
                if cleanup_failures:
                    detail = ",".join(cleanup_failures)
                    if active_error is not None:
                        active_error.add_note(f"V20 diagnostic cleanup failures: {detail}")
                    else:
                        raise RuntimeError(f"V20 diagnostic cleanup failed: {detail}")


def run() -> None:
    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    accepted = (
        [],
        ["--preflight-only"],
        ["--dayops-smoke-test"],
        ["--advanced-operations-smoke-test"],
        ["--native-startup-smoke-test"],
    )
    if sys.argv[1:] not in accepted:
        raise RuntimeError("Onyx Live V20 launcher arguments are invalid")
    legacy = _v19_contract()
    native_smoke = sys.argv[1:] == ["--native-startup-smoke-test"]
    single_instance, proceed = legacy["_acquire_gui_mutex"](
        () if native_smoke else tuple(sys.argv[1:]),
        factory=legacy["_BoundedNativeSmokeMutexV19"] if native_smoke else None,
    )
    if not proceed:
        return
    governance_mutex = (
        legacy["_acquire_governance_runtime_mutex"]() if not sys.argv[1:] else None
    )
    controller = None
    frozen_diagnostic = False
    try:
        if native_smoke:
            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with LOG_PATH.open("a", encoding="utf-8", buffering=1) as log:
                print(
                    f"\n[{datetime.now(timezone.utc).isoformat()}] "
                    "Onyx native startup smoke entering stable V20 launcher",
                    file=log,
                )
                payload = legacy["_run_native_startup_diagnostic"]()
                print(
                    "Onyx native startup smoke passed "
                    f"contract={payload.get('contract')} status={payload.get('status')}",
                    file=log,
                )
            frozen_diagnostic = bool(
                getattr(sys, "frozen", False) or getattr(sys, "_MEIPASS", None)
            )
        elif sys.argv[1:]:
            _run_bounded_diagnostic(tuple(sys.argv[1:]))
            frozen_diagnostic = bool(
                getattr(sys, "frozen", False) or getattr(sys, "_MEIPASS", None)
            )
        else:
            from core.onyx_live_activation_v15 import verify_activation_prerequisites
            from core.onyx_live_activation_v20 import activate_main

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
                print(f"\n[{datetime.now(timezone.utc).isoformat()}] Onyx Live V20 starting")
                print(f"Advanced Operations: {controller.advanced_operations_capability}")
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
    if frozen_diagnostic:
        if sys.stdout is not None:
            sys.stdout.flush()
        if sys.stderr is not None:
            sys.stderr.flush()
        os._exit(0)


if __name__ == "__main__":
    run()
