"""Explicit default-off launcher for the current Onyx stack on POSIX."""

from __future__ import annotations

import os
import sys
from contextlib import nullcontext
from pathlib import Path

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])).resolve()


def _portable_runtime_root() -> Path:
    """Return a centrally validated root; creation/pinning belongs to the boundary."""

    from core.paths import (
        data_root,
        is_frozen,
        private_control_plane_runtime_dir,
        resource_root,
    )

    configured = data_root()
    if is_frozen() or configured != resource_root():
        return configured / "runtime"
    return private_control_plane_runtime_dir()


class _PreflightUI:
    def __init__(self) -> None:
        self.muted = True
        self.current_file = None
        self.trusted_ui_prompts = 0

    def write_log(self, _value: str) -> None:
        pass

    def set_state(self, _value: str) -> None:
        pass


def _acquire_single_instance(arguments: tuple[str, ...]):
    from core.host_security_boundary_v1 import HostSecurityBoundaryBusy
    from core.posix_single_instance_v1 import PosixSingleInstanceV1
    from core.posix_trusted_directory_v1 import PosixTrustedDirectoryV1

    boundary = PosixTrustedDirectoryV1(
        root=_portable_runtime_root() / "portable-current-launcher-v1",
        enabled=True,
    )
    lease = PosixSingleInstanceV1(directory=boundary)
    try:
        acquired = lease.acquire()
    except BaseException:
        boundary.close()
        raise
    if acquired:
        return boundary, lease
    lease.close()
    boundary.close()
    if arguments:
        raise HostSecurityBoundaryBusy("portable_current_diagnostic_busy")
    return None, None


def _run_preflight() -> None:
    from core.native_startup_smoke_v1 import (
        ExternalCallCountersV1,
        _cleanup_host,
        external_call_boundary_v1,
    )

    calls = ExternalCallCountersV1()
    controller = None
    instance = None
    onyx_main = None
    original_runtime_dir = None
    phase11_boundary = None
    with external_call_boundary_v1(counters=calls):
        import main as imported_main

        onyx_main = imported_main
        from core.posix_trusted_directory_v1 import PosixTrustedDirectoryV1

        phase11_boundary = PosixTrustedDirectoryV1(
            root=_portable_runtime_root() / "phase11-authority-v1",
            enabled=True,
        )
        phase11_runtime = phase11_boundary.path
        original_runtime_dir = imported_main.runtime_dir
        imported_main.runtime_dir = lambda: phase11_runtime
        with nullcontext():
            active_error: BaseException | None = None
            try:
                from core.onyx_portable_current_activation_v1 import activate_main

                controller = activate_main(imported_main)
                instance = controller.instantiate_live(_PreflightUI())
                if any((calls.network, calls.provider, calls.process)):
                    raise RuntimeError(
                        "portable current preflight crossed provider-free boundary"
                    )
                print(
                    "ONYX_PORTABLE_CURRENT_V1_PREFLIGHT_OK "
                    "activation=v19 capability_limited=true "
                    "native_evidence_required=true "
                    f"network_calls={calls.network} "
                    f"provider_calls={calls.provider} "
                    f"process_calls={calls.process}",
                    flush=True,
                )
            except BaseException as exc:
                active_error = exc
                if (
                    type(exc).__name__ == "PortableCurrentActivationV1Error"
                    and "v16_descriptor_governance_unavailable" in str(exc)
                ):
                    print(
                        "ONYX_PORTABLE_CURRENT_V1_UNAVAILABLE "
                        "declared_activation=v19 highest_proven_activation=none "
                        "boundary_reached=pre_v16 next_unimplemented_activation=v16 "
                        "reason=v16_descriptor_governance_unavailable "
                        "capability_limited=true parity=false",
                        flush=True,
                    )
                raise
            finally:
                failures = _cleanup_host(
                    ui=None,
                    controller=controller,
                    onyx_main=onyx_main,
                    original_runtime_dir=original_runtime_dir,
                    instance=instance,
                )
                if failures:
                    detail = ",".join(failures)
                    if active_error is not None:
                        active_error.add_note(
                            f"portable current cleanup failures: {detail}"
                        )
                    else:
                        raise RuntimeError(
                            f"portable current cleanup failed: {detail}"
                        )
                if phase11_boundary is not None:
                    phase11_boundary.close()


def run() -> None:
    arguments = tuple(sys.argv[1:])
    if arguments not in ((), ("--preflight-only",), ("--native-startup-smoke-test",)):
        raise RuntimeError("Onyx portable-current launcher arguments are invalid")
    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    boundary, single_instance = _acquire_single_instance(arguments)
    controller = None
    try:
        if boundary is None:
            return
        if arguments == ("--native-startup-smoke-test",):
            from core.native_startup_smoke_v1 import (
                run_terminal_native_startup_smoke_v1,
            )

            run_terminal_native_startup_smoke_v1()
            return
        if arguments == ("--preflight-only",):
            _run_preflight()
            return

        from core.onyx_portable_current_activation_v1 import activate_main

        from core.posix_trusted_directory_v1 import PosixTrustedDirectoryV1

        phase11_boundary = PosixTrustedDirectoryV1(
            root=_portable_runtime_root() / "phase11-authority-v1",
            enabled=True,
        )
        phase11_runtime = phase11_boundary.path
        import main as onyx_main

        onyx_main.runtime_dir = lambda: phase11_runtime
        controller = activate_main(onyx_main)
        print("Onyx portable-current V1 starting", flush=True)
        onyx_main.main()
    finally:
        try:
            if controller is not None:
                controller.rollback_all()
        finally:
            try:
                if single_instance is not None:
                    single_instance.close()
            finally:
                try:
                    if "phase11_boundary" in locals():
                        phase11_boundary.close()
                finally:
                    if boundary is not None:
                        boundary.close()


if __name__ == "__main__":
    run()
