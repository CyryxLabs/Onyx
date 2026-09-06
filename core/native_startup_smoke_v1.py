"""Provider-free native startup proof for packaged Onyx hosts.

The smoke deliberately stops before microphone capture, model connection, or
the Qt event loop.  It still constructs the real window and the real OnyxLive
host through the highest activation supported by the native platform.

The external-I/O fence is intentionally described as a *best-effort Python
runtime* boundary.  It intercepts the common Python, HTTP-client, Qt, provider,
browser, and child-process seams that are present in the frozen process; it is
not an operating-system sandbox and must never be reported as one.
"""

from __future__ import annotations

import http.client
import ctypes.util
import json
import multiprocessing.process
import os
import platform
import re
import socket
import stat
import subprocess
import sys
import threading
import urllib.request
import webbrowser
from contextlib import contextmanager, nullcontext
from pathlib import Path
from types import ModuleType
from typing import Any, Final, Iterator

NATIVE_STARTUP_SMOKE_ARGUMENT: Final = "--native-startup-smoke-test"
NATIVE_STARTUP_SMOKE_OUTPUT_ENV: Final = "ONYX_NATIVE_STARTUP_SMOKE_OUTPUT"
NATIVE_STARTUP_SMOKE_CONTRACT: Final = "OnyxNativeStartupSmoke.v1"
TERMINAL_FENCE_EVIDENCE_KEY: Final = "terminal_fence_until_process_exit"
INTERCEPTION_SCOPE: Final = "best_effort_python_runtime"
PORTABLE_CURRENT_NEGATIVE_BOUNDARY_GATE: Final = (
    "portable_current_negative_boundary_gate"
)
POSIX_OWNER_BACKEND_PROBE_SURFACE: Final = (
    "process:subprocess.run:posix_owner_backend_read_only"
)
POSIX_OWNER_BACKEND_PROBE_MAX_CALLS: Final = 5
_POSIX_OWNER_BACKEND_TOOLS: Final = frozenset(
    {"/usr/bin/secret-tool", "/bin/secret-tool"}
)
_POSIX_OWNER_LOOKUP_REFERENCES: Final = frozenset(
    {
        ("CyryxLabs.Onyx.OwnerProfileV8", "journal-key-primary"),
        (
            "Onyx.OwnerProfileChainHead.v1",
            "owner-ebb5c3055dbe465c3cfa9457bad77797",
        ),
    }
)
_UNSET: Final = object()
_PROVIDER_FREE_CREDENTIAL_SENTINEL: Final = (
    "onyx-native-startup-smoke-provider-disabled"
)


class NativeStartupSmokeError(RuntimeError):
    """The native host could not reach the bounded startup contract."""


class _DiagnosticSecretVaultV1:
    """Process-local byte vault used only by the isolated Governance smoke."""

    def __init__(self, key: tuple[str, str], storage: dict[tuple[str, str], bytes]):
        self._key = key
        self._storage = storage

    def get_bytes(self) -> bytes | None:
        value = self._storage.get(self._key)
        return None if value is None else bytes(value)

    def set_bytes(self, value: bytes | bytearray) -> None:
        raw = bytes(value)
        if not raw:
            raise NativeStartupSmokeError("diagnostic vault refuses empty secrets")
        self._storage[self._key] = raw

    def delete(self) -> bool:
        return self._storage.pop(self._key, None) is not None


class _DiagnosticGovernanceVaultModuleV1:
    """Narrow proxy that replaces only Governance's native-vault constructor."""

    def __init__(self, original: ModuleType):
        self._original = original
        self._storage: dict[tuple[str, str], bytes] = {}
        self.SecretReference = original.SecretReference

    def NativeSecretVault(self, reference: object, **_kwargs: object) -> object:
        service = getattr(reference, "service", None)
        account = getattr(reference, "account", None)
        if type(service) is not str or type(account) is not str:
            raise NativeStartupSmokeError("diagnostic vault reference is invalid")
        return _DiagnosticSecretVaultV1((service, account), self._storage)

    def __getattr__(self, name: str) -> object:
        return getattr(self._original, name)


class ExternalCallCountersV1:
    """Attempt counters and the exact in-process seams covered by the fence."""

    def __init__(self) -> None:
        self.network = 0
        self.provider = 0
        self.process = 0
        self.secure_backend_probe = 0
        # Boundary capabilities and tickets belong to this exact smoke run and
        # are isolated per thread.  Nothing is published as process-global
        # authorization state.
        self._boundary_state = threading.local()
        self.surfaces: dict[str, set[str]] = {
            "network": set(),
            "provider": set(),
            "process": set(),
        }

    def evidence(self) -> dict[str, object]:
        return {
            "scope": INTERCEPTION_SCOPE,
            "network_surfaces": sorted(self.surfaces["network"]),
            "process_surfaces": sorted(self.surfaces["process"]),
            "provider_surfaces": sorted(self.surfaces["provider"]),
            "secure_backend_probe_calls": self.secure_backend_probe,
            "secure_backend_probe_surfaces": (
                [POSIX_OWNER_BACKEND_PROBE_SURFACE] if self.secure_backend_probe else []
            ),
        }


class _ProviderDeniedAdapterV1:
    """Host-local provider adapter that leaves the SDK module untouched."""

    def __init__(
        self,
        delegate: object,
        counters: ExternalCallCountersV1,
    ) -> None:
        self._delegate = delegate
        self._counters = counters

    def Client(self, *_args: object, **_kwargs: object) -> None:
        self._counters.provider += 1
        raise NativeStartupSmokeError("native startup attempted provider construction")

    def __getattr__(self, name: str) -> object:
        return getattr(self._delegate, name)


def _optional_owner(module_name: str, attribute: str) -> object | None:
    module = sys.modules.get(module_name)
    return getattr(module, attribute, None) if module is not None else None


def _is_exact_posix_owner_backend_probe_v1(
    args: tuple[object, ...],
    kwargs: dict[str, object],
) -> bool:
    """Recognize only the bounded read-only Secret Service probe contract."""

    if len(args) != 1 or type(args[0]) is not list:
        return False
    argv = args[0]
    if not all(type(item) is str for item in argv):
        return False
    if not argv or argv[0] not in _POSIX_OWNER_BACKEND_TOOLS:
        return False
    expected_kwargs = {
        "input": None,
        "text": True,
        "capture_output": True,
        "timeout": 15,
        "check": False,
        "shell": False,
    }
    if set(kwargs) != set(expected_kwargs):
        return False
    for name, expected in expected_kwargs.items():
        if kwargs[name] is not expected and kwargs[name] != expected:
            return False
        if type(expected) is bool and type(kwargs[name]) is not bool:
            return False
        if type(expected) is int and type(kwargs[name]) is not int:
            return False
    tail = argv[1:]
    if len(tail) == 5 and tail[0:2] == ["lookup", "service"]:
        return (
            tail[3] == "account"
            and (tail[2], tail[4]) in _POSIX_OWNER_LOOKUP_REFERENCES
        )
    if len(tail) != 6 or tail[:5] != [
        "search",
        "--all",
        "service",
        "Onyx.NativeVault.HealthProbe",
        "account",
    ]:
        return False
    return bool(
        re.fullmatch(
            rf"probe-{os.getpid()}-[0-9a-f]{{32}}",
            tail[5],
        )
    )


@contextmanager
def posix_owner_backend_probe_capability_v1(
    counters: ExternalCallCountersV1,
) -> Iterator[None]:
    """Activate the exact Linux read-only probe capability inside one fence."""

    state = counters._boundary_state
    boundary = getattr(state, "active_boundary", None)
    if (
        boundary is None
        or not boundary["allow_posix_owner_backend_probe"]
        or platform.system() != "Linux"
        or getattr(state, "owner_probe_phase", None) is not None
    ):
        raise NativeStartupSmokeError(
            "POSIX owner backend probe capability is unavailable"
        )
    phase = {
        "boundary": boundary["capability"],
        "capability": object(),
    }
    state.owner_probe_phase = phase
    try:
        yield
    finally:
        if getattr(state, "owner_probe_phase", None) is phase:
            state.owner_probe_phase = None


@contextmanager
def _provider_call_boundary_v1(
    host_module: object,
    counters: ExternalCallCountersV1,
    *,
    restore_on_exit: bool = True,
) -> Iterator[None]:
    """Fence provider construction after the continuously fenced import."""

    host_genai = getattr(host_module, "genai", None)
    if host_genai is None:
        yield
        return
    try:
        setattr(
            host_module,
            "genai",
            _ProviderDeniedAdapterV1(host_genai, counters),
        )
    except (AttributeError, TypeError):
        yield
        return
    counters.surfaces["provider"].add("provider:google.genai.Client")
    try:
        yield
    finally:
        if restore_on_exit:
            setattr(host_module, "genai", host_genai)


@contextmanager
def external_call_boundary_v1(
    *,
    counters: ExternalCallCountersV1 | None = None,
    host_module: object | None = None,
    allow_posix_owner_backend_probe: bool = False,
    _restore_on_exit: bool = True,
) -> Iterator[ExternalCallCountersV1]:
    """Deny common in-process external-I/O seams and restore every patch.

    ``subprocess.Popen`` remains subclassable while fenced: the replacement is
    a guard class derived from the authentic Popen class.  Its constructor is
    denied during import and accepts only a single-use, exact-argv ticket
    emitted by the guarded Linux read-only probe path during runtime.
    """

    observed = counters or ExternalCallCountersV1()
    originals: list[tuple[object, str, object]] = []
    boundary_capability = object()
    boundary_state = observed._boundary_state
    if getattr(boundary_state, "active_boundary", None) is not None:
        raise NativeStartupSmokeError("external-call boundary cannot be nested")

    def replace(owner: object | None, name: str, value: object, surface: str) -> None:
        if owner is None or not hasattr(owner, name):
            return
        try:
            original = getattr(owner, name)
            setattr(owner, name, value)
        except (AttributeError, TypeError):
            return
        originals.append((owner, name, original))
        category = surface.split(":", 1)[0]
        observed.surfaces[category].add(surface)

    def network_denied(*_args: object, **_kwargs: object) -> None:
        observed.network += 1
        raise NativeStartupSmokeError("native startup attempted network I/O")

    def process_denied(*_args: object, **_kwargs: object) -> None:
        observed.process += 1
        raise NativeStartupSmokeError("native startup attempted a child process")

    original_popen = subprocess.Popen
    original_run = subprocess.run

    class GuardedPopenV1(original_popen):
        def __init__(self, *args: object, **kwargs: object) -> None:
            ticket = getattr(boundary_state, "owner_probe_ticket", None)
            phase = getattr(boundary_state, "owner_probe_phase", None)
            expected_kwargs = {
                "text": True,
                "shell": False,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
            }
            if (
                ticket is not None
                and phase is not None
                and ticket["boundary"] is boundary_capability
                and phase["boundary"] is boundary_capability
                and ticket["phase"] is phase["capability"]
                and ticket["popen"] is True
                and len(args) == 1
                and type(args[0]) is list
                and tuple(args[0]) == ticket["argv"]
                and set(kwargs) == set(expected_kwargs)
                and all(
                    kwargs[name] is expected
                    for name, expected in expected_kwargs.items()
                )
            ):
                # Consume before authentic construction.  Re-entrancy and an
                # identical second construction therefore remain denied.
                ticket["popen"] = False
                super().__init__(*args, **kwargs)
                return
            process_denied(*args, **kwargs)

    GuardedPopenV1.__name__ = original_popen.__name__
    GuardedPopenV1.__qualname__ = original_popen.__qualname__
    GuardedPopenV1.__module__ = original_popen.__module__

    def run_guarded(*args: object, **kwargs: object) -> object:
        phase = getattr(boundary_state, "owner_probe_phase", None)
        if (
            allow_posix_owner_backend_probe
            and platform.system() == "Linux"
            and observed.secure_backend_probe < POSIX_OWNER_BACKEND_PROBE_MAX_CALLS
            and phase is not None
            and phase["boundary"] is boundary_capability
            and getattr(boundary_state, "owner_probe_ticket", None) is None
            and _is_exact_posix_owner_backend_probe_v1(args, kwargs)
        ):
            observed.secure_backend_probe += 1
            ticket = {
                "boundary": boundary_capability,
                "phase": phase["capability"],
                "argv": tuple(args[0]),
                "popen": True,
            }
            boundary_state.owner_probe_ticket = ticket
            try:
                return original_run(*args, **kwargs)
            finally:
                if getattr(boundary_state, "owner_probe_ticket", None) is ticket:
                    boundary_state.owner_probe_ticket = None
        return process_denied(*args, **kwargs)

    original_find_library = ctypes.util.find_library

    def find_library_guarded(name: object) -> str | None:
        # sounddevice imports PortAudio through ctypes.  Linux's stock
        # find_library implementation shells out to ldconfig, so provide the
        # stable loader soname directly rather than opening an import-time
        # process window.  Other Linux discovery remains fail-closed.
        if platform.system() == "Linux":
            if name == "portaudio":
                return "libportaudio.so.2"
            return process_denied(name)  # type: ignore[return-value]
        return original_find_library(name)  # type: ignore[arg-type]

    # Install the subclassable constructor guard before the wider seam set.
    # It remains installed continuously across import and runtime activation.
    replace(
        subprocess,
        "Popen",
        GuardedPopenV1,
        "process:subprocess.Popen",
    )
    replace(
        ctypes.util,
        "find_library",
        find_library_guarded,
        "process:ctypes.util.find_library",
    )

    # Standard-library transport and DNS seams.
    replace(
        socket, "create_connection", network_denied, "network:socket.create_connection"
    )
    replace(socket, "getaddrinfo", network_denied, "network:socket.getaddrinfo")
    for name in (
        "gethostbyaddr",
        "gethostbyname",
        "gethostbyname_ex",
        "getnameinfo",
    ):
        replace(socket, name, network_denied, f"network:socket.{name}")
    replace(socket.socket, "connect", network_denied, "network:socket.socket.connect")
    replace(
        socket.socket, "connect_ex", network_denied, "network:socket.socket.connect_ex"
    )
    for name in ("send", "sendall", "sendto", "sendmsg"):
        replace(
            socket.socket,
            name,
            network_denied,
            f"network:socket.socket.{name}",
        )
    replace(urllib.request, "urlopen", network_denied, "network:urllib.request.urlopen")
    replace(
        urllib.request.OpenerDirector,
        "open",
        network_denied,
        "network:urllib.request.OpenerDirector.open",
    )
    replace(
        http.client.HTTPConnection,
        "connect",
        network_denied,
        "network:http.client.HTTPConnection.connect",
    )
    replace(
        http.client.HTTPSConnection,
        "connect",
        network_denied,
        "network:http.client.HTTPSConnection.connect",
    )

    # Third-party clients are patched only when already imported.  This keeps
    # the smoke itself from importing optional runtimes merely to inspect them.
    replace(
        _optional_owner("requests.sessions", "Session"),
        "request",
        network_denied,
        "network:requests.Session.request",
    )
    replace(
        _optional_owner("httpx", "Client"),
        "request",
        network_denied,
        "network:httpx.Client.request",
    )
    replace(
        _optional_owner("httpx", "AsyncClient"),
        "request",
        network_denied,
        "network:httpx.AsyncClient.request",
    )
    replace(
        _optional_owner("aiohttp.client", "ClientSession"),
        "_request",
        network_denied,
        "network:aiohttp.ClientSession._request",
    )
    replace(
        _optional_owner("PySide6.QtNetwork", "QNetworkAccessManager"),
        "createRequest",
        network_denied,
        "network:Qt.QNetworkAccessManager.createRequest",
    )

    # Process and browser launch seams.
    replace(
        subprocess,
        "run",
        run_guarded,
        "process:subprocess.run",
    )
    for name in ("call", "check_call", "check_output"):
        replace(subprocess, name, process_denied, f"process:subprocess.{name}")
    replace(os, "system", process_denied, "process:os.system")
    replace(os, "startfile", process_denied, "process:os.startfile")
    for name in (
        "spawnl",
        "spawnle",
        "spawnlp",
        "spawnlpe",
        "spawnv",
        "spawnve",
        "spawnvp",
        "spawnvpe",
    ):
        replace(os, name, process_denied, f"process:os.{name}")
    replace(
        multiprocessing.process.BaseProcess,
        "start",
        process_denied,
        "process:multiprocessing.BaseProcess.start",
    )
    for name in ("open", "open_new", "open_new_tab"):
        replace(webbrowser, name, process_denied, f"process:webbrowser.{name}")
    replace(
        _optional_owner("PySide6.QtCore", "QProcess"),
        "start",
        process_denied,
        "process:Qt.QProcess.start",
    )
    replace(
        _optional_owner("PySide6.QtCore", "QProcess"),
        "startDetached",
        process_denied,
        "process:Qt.QProcess.startDetached",
    )

    # Provider construction is fenced through the host's injected SDK
    # reference.  Never replace google.genai.Client itself: other threads and
    # components in the process must continue to see the authentic SDK symbol.
    host_genai = getattr(host_module, "genai", None)
    if host_module is not None and host_genai is not None:
        replace(
            host_module,
            "genai",
            _ProviderDeniedAdapterV1(host_genai, observed),
            "provider:google.genai.Client",
        )

    boundary_state.active_boundary = {
        "capability": boundary_capability,
        "allow_posix_owner_backend_probe": allow_posix_owner_backend_probe,
    }
    active_error: BaseException | None = None
    try:
        yield observed
    except BaseException as exc:
        active_error = exc
        raise
    finally:
        if _restore_on_exit:
            restore_failures: list[str] = []
            boundary_state.owner_probe_phase = None
            boundary_state.owner_probe_ticket = None
            # Restore Popen last so an authentic subprocess.run exposed during
            # reversible teardown still reaches a denying constructor.
            ordered = [
                item
                for item in reversed(originals)
                if not (item[0] is subprocess and item[1] == "Popen")
            ]
            ordered.extend(
                item
                for item in reversed(originals)
                if item[0] is subprocess and item[1] == "Popen"
            )
            for owner, name, original in ordered:
                try:
                    setattr(owner, name, original)
                except BaseException as exc:  # restore every reversible seam
                    restore_failures.append(
                        f"{type(owner).__name__}.{name}:{type(exc).__name__}"
                    )
            boundary_state.active_boundary = None
            if restore_failures:
                detail = ",".join(restore_failures)
                if active_error is not None:
                    active_error.add_note(
                        f"external-call boundary restore failures: {detail}"
                    )
                else:
                    raise NativeStartupSmokeError(
                        f"external-call boundary restore failed: {detail}"
                    )


def _lexical_absolute_output(raw_output: str) -> Path:
    """Return an absolute lexical path without following filesystem links."""

    return Path(os.path.abspath(raw_output))


def _require_existing_posix_parent_v1(parent: Path) -> None:
    """Walk the lexical parent with dirfds and reject every linked component."""

    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    descriptor = -1
    try:
        descriptor = os.open("/", flags)
        for component in parent.parts[1:]:
            child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise NativeStartupSmokeError(
                "native startup smoke output parent must preexist"
            )
    except (FileNotFoundError, NotADirectoryError, OSError) as exc:
        raise NativeStartupSmokeError(
            "native startup smoke output parent must preexist without symlinks"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _write_result(output: Path, payload: dict[str, object]) -> None:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if os.name == "posix":
        from core.host_security_boundary_v1 import HostSecurityBoundaryError
        from core.posix_trusted_directory_v1 import PosixTrustedDirectoryV1

        _require_existing_posix_parent_v1(output.parent)
        try:
            # The boundary repeats the O_NOFOLLOW descriptor walk, pins the
            # lexical parent identity, and publishes the leaf relative to that
            # descriptor.  No resolved path is used as publication authority.
            with PosixTrustedDirectoryV1(root=output.parent, enabled=True) as boundary:
                with boundary.session() as session:
                    session.publish_replace(output.name, encoded)
        except HostSecurityBoundaryError as exc:
            raise NativeStartupSmokeError(
                "native startup smoke output path is not trusted"
            ) from exc
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    with temporary.open("wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(output)


def _external_agent_unavailable(**_binding: object) -> object:
    """Retained for bounded legacy diagnostics; V24 exposes no factory seam."""

    from core.external_agent_adapter_v1 import ExternalAgentUnavailable

    raise ExternalAgentUnavailable("native_startup_smoke_provider_free")


def _prepare_windows_v24(workspace: Path) -> dict[str, str]:
    from core.onyx_live_activation_v24 import (
        CONTROL_FLAGS,
        exact_activation_environment,
    )

    result = dict(os.environ)
    for name in CONTROL_FLAGS:
        result.pop(name, None)
    # V24 deliberately exposes no V23/V22 option injection seam.  Its exact
    # environment descends through V23 with the authenticated default authority
    # contract, which keeps the Windows executable sandbox enabled.  Passing a
    # legacy keyword here both violated that boundary and made the frozen
    # diagnostic fail before it could emit its bounded JSON receipt.
    result.update(exact_activation_environment((workspace,)))
    return result


def _prepare_portable_v8() -> dict[str, str]:
    from core.onyx_live_activation_v8 import (
        CONTROL_FLAGS,
        exact_activation_environment,
    )

    result = dict(os.environ)
    for name in CONTROL_FLAGS:
        result.pop(name, None)
    result.update(exact_activation_environment())
    return result


def _prepare_portable_current_v1(
    workspace: Path,
    *,
    workspace_boundary: object,
) -> dict[str, str]:
    from core.onyx_portable_current_activation_v1 import (
        exact_activation_environment_v1,
    )

    return exact_activation_environment_v1(
        workspace,
        environ=os.environ,
        workspace_boundary=workspace_boundary,
    )


def _provider_free_environment_v1(
    environment: dict[str, str],
) -> dict[str, str]:
    """Avoid native-vault probes while the provider constructor is denied.

    The native UI checks only whether a credential exists when choosing its
    initial setup projection.  During this bounded smoke, provider creation is
    denied by the host-local adapter, so a non-secret sentinel is sufficient
    and prevents Linux Secret Service helpers from becoming false-positive
    child-process attempts.  The caller-owned mapping is never mutated and the
    outer smoke coordinator restores the process environment exactly.
    """

    result = dict(environment)
    result.pop("GOOGLE_API_KEY", None)
    result["GEMINI_API_KEY"] = _PROVIDER_FREE_CREDENTIAL_SENTINEL
    return result


def _activation_for_system(
    system: str,
    *,
    portable_current: bool = False,
) -> str:
    from core.native_activation_contract_v1 import (
        NativeActivationContractError,
        activation_contract_for_system_v1,
    )

    try:
        contract = activation_contract_for_system_v1(
            system,
            portable_current=portable_current,
        )
    except NativeActivationContractError as exc:
        raise NativeStartupSmokeError(
            f"unsupported native startup host: {system}"
        ) from exc
    return str(contract["smoke_activation"])


def _authenticated_windows_v24_host_v1(
    controller: object,
    instance: object,
    host_module: object,
) -> bool:
    """Accept only the exact live host guarded by this V24 controller.

    V24 deliberately replaces the instance's exact class with a unique
    per-instance subclass so the final tool dispatcher cannot be shadowed.
    Checking only ``isinstance`` would also accept an unrelated subclass, so
    the smoke authenticates the controller-owned binding record and both
    class-level guard descriptors instead.
    """

    from core import onyx_live_activation_v24 as v24

    if (
        type(host_module) is not ModuleType
        or type(controller) is not v24.OnyxLiveActivationV24
        or getattr(controller, "_installed", None) is not True
        or getattr(controller, "_rollback_pending", None) is not False
    ):
        return False
    contract = getattr(controller, "contract", None)
    host_type = getattr(host_module, "OnyxLive", None)
    if (
        type(contract) is not v24.HostContractV24
        or contract.module is not host_module
        or getattr(host_module, v24.HOST_MARKER, None) is not controller
        or type(host_type) is not type
    ):
        return False
    bindings = getattr(controller, "_bindings", None)
    if type(bindings) is not list or len(bindings) != 1:
        return False
    binding = bindings[0]
    guarded_class = type(instance)
    instance_dict = getattr(instance, "__dict__", None)
    return bool(
        type(binding) is v24._BindingV24
        and binding.instance is instance
        and binding.previous_class is host_type
        and binding.guarded_class is guarded_class
        and binding.class_restored is False
        and guarded_class.__bases__ == (host_type,)
        and guarded_class.__module__ == host_type.__module__
        and guarded_class.__dict__.get("_execute_tool") is binding.owned_dispatch
        and type(binding.owned_dispatch) is v24._ProtectedDispatchV24
        and guarded_class.__dict__.get("__setattr__") is binding.owned_setattr
        and type(instance_dict) is dict
        and "_execute_tool" not in instance_dict
    )


def _cleanup_host(
    *,
    ui: object | None,
    controller: object | None,
    onyx_main: object | None,
    original_runtime_dir: object,
    instance: object | None = None,
    paths_module: object | None = None,
    original_private_control_plane_runtime_dir: object = _UNSET,
    governance_module: object | None = None,
    original_governance_native_vault: object = _UNSET,
    control_plane_module: object | None = None,
    original_control_plane_runtime_dir: object = _UNSET,
) -> tuple[str, ...]:
    """Attempt every cleanup step and return compact failure evidence."""

    failures: list[str] = []

    def attempt(label: str, action: object) -> None:
        try:
            action()  # type: ignore[operator]
        except BaseException as exc:
            failures.append(f"{label}:{type(exc).__name__}")

    if instance is not None:
        stop_phase5 = getattr(instance, "_stop_phase5_session", None)
        if callable(stop_phase5):
            attempt(
                "host.phase5.stop",
                lambda: stop_phase5("native-startup-smoke"),
            )
        phase11 = getattr(instance, "_phase11_missions", None)
        if phase11 is not None:
            begin_shutdown = getattr(phase11, "begin_shutdown", None)
            if callable(begin_shutdown):
                attempt("host.phase11.begin_shutdown", begin_shutdown)
        worker = getattr(instance, "_mission_worker", None)
        stop_worker = getattr(worker, "stop", None)
        if callable(stop_worker):
            try:
                stopped = stop_worker(15.0)
                if stopped is not True:
                    failures.append("host.worker.stop:UnconfirmedStop")
            except BaseException as exc:
                failures.append(f"host.worker.stop:{type(exc).__name__}")
        if phase11 is not None:
            close_phase11 = getattr(phase11, "close", None)
            if callable(close_phase11):
                attempt("host.phase11.close", lambda: close_phase11(15.0))
    if ui is not None:
        window = getattr(ui, "_win", None)
        app = getattr(ui, "_app", None)
        if window is not None:
            attempt("ui.close", window.close)
        if app is not None:
            attempt("ui.processEvents", app.processEvents)
    if controller is not None:
        rollback = getattr(controller, "rollback_all", None)
        if callable(rollback):
            attempt("activation.rollback_all", rollback)
    if onyx_main is not None and original_runtime_dir is not _UNSET:
        attempt(
            "main.runtime_dir.restore",
            lambda: setattr(onyx_main, "runtime_dir", original_runtime_dir),
        )
    if (
        paths_module is not None
        and original_private_control_plane_runtime_dir is not _UNSET
    ):
        attempt(
            "paths.private_control_plane_runtime_dir.restore",
            lambda: setattr(
                paths_module,
                "private_control_plane_runtime_dir",
                original_private_control_plane_runtime_dir,
            ),
        )
    if governance_module is not None and original_governance_native_vault is not _UNSET:
        attempt(
            "governance.native_vault.restore",
            lambda: setattr(
                governance_module,
                "native_vault",
                original_governance_native_vault,
            ),
        )
    if (
        control_plane_module is not None
        and original_control_plane_runtime_dir is not _UNSET
    ):
        attempt(
            "control_plane.private_control_plane_runtime_dir.restore",
            lambda: setattr(
                control_plane_module,
                "private_control_plane_runtime_dir",
                original_control_plane_runtime_dir,
            ),
        )
    return tuple(failures)


def _run_host(
    output: Path,
    *,
    terminal_fence: bool = False,
) -> dict[str, object]:
    from core.native_activation_contract_v1 import activation_contract_for_system_v1

    system = platform.system()
    from core.onyx_portable_current_activation_v1 import (
        FEATURE_FLAG as PORTABLE_CURRENT_FLAG,
    )

    portable_current = (
        system in {"Darwin", "Linux"} and os.environ.get(PORTABLE_CURRENT_FLAG) == "1"
    )
    activation = _activation_for_system(
        system,
        portable_current=portable_current,
    )
    activation_contract = activation_contract_for_system_v1(
        system,
        portable_current=portable_current,
    )
    data_root = Path(os.environ["ONYX_DATA_DIR"]).absolute()
    if system in {"Darwin", "Linux"}:
        # The stable launcher writes its diagnostic log before this component
        # smoke starts. On POSIX, normalize the complete managed data layout to
        # private owner-only modes before descriptor-bound validation. This
        # repairs prior 0755 application directories but never accepts links or
        # foreign ownership.
        from core.paths import ensure_data_layout

        ensure_data_layout()
    workspace = data_root / "workspace"
    data_boundary: object | None = None
    workspace_boundary: object | None = None
    if system in {"Darwin", "Linux"}:
        from core.posix_trusted_directory_v1 import PosixTrustedDirectoryV1

        if data_root.is_symlink() or not data_root.is_dir():
            raise NativeStartupSmokeError(
                "native startup data root must preexist without symlinks"
            )
        data_boundary = PosixTrustedDirectoryV1(root=data_root, enabled=True)
        with data_boundary.session() as session:
            session.ensure_directory("workspace")
            session.ensure_directory("runtime/phase11-authority-v1")
        workspace_boundary = PosixTrustedDirectoryV1(
            root=workspace,
            enabled=True,
        )
    else:
        workspace.mkdir(parents=True, exist_ok=True)
    if system == "Windows":
        environment = _prepare_windows_v24(workspace)
    elif portable_current:
        environment = _prepare_portable_current_v1(
            workspace,
            workspace_boundary=workspace_boundary,
        )
    else:
        environment = _prepare_portable_v8()
    environment = _provider_free_environment_v1(environment)
    os.environ.clear()
    os.environ.update(environment)

    ui: object | None = None
    controller: Any = None
    onyx_main: object | None = None
    original_runtime_dir: object = _UNSET
    paths_module: object | None = None
    original_private_control_plane_runtime_dir: object = _UNSET
    governance_module: object | None = None
    original_governance_native_vault: object = _UNSET
    control_plane_module: object | None = None
    original_control_plane_runtime_dir: object = _UNSET
    instance: object | None = None
    calls = ExternalCallCountersV1()

    # One continuous fence spans import and runtime. Popen is a denying guard
    # class, so ``main`` can declare compatibility subclasses without gaining
    # a process-launch window.
    with external_call_boundary_v1(
        counters=calls,
        allow_posix_owner_backend_probe=(portable_current and system == "Linux"),
        _restore_on_exit=not terminal_fence,
    ):
        import main as imported_main

        onyx_main = imported_main
        probe_capability = (
            posix_owner_backend_probe_capability_v1(calls)
            if portable_current and system == "Linux"
            else nullcontext()
        )
        with (
            _provider_call_boundary_v1(
                imported_main,
                calls,
                restore_on_exit=not terminal_fence,
            ),
            probe_capability,
        ):
            active_error: BaseException | None = None
            try:
                if system == "Windows":
                    from core.onyx_live_activation_v24 import activate_main
                    from core import paths as imported_paths

                    phase11_runtime = data_root / "runtime" / "phase11-authority-v1"
                    phase11_runtime.mkdir(parents=True, exist_ok=True)
                    original_runtime_dir = imported_main.runtime_dir
                    imported_main.runtime_dir = lambda: phase11_runtime.resolve()
                    controller = activate_main(imported_main)
                    # V7 activation attests the installed owner identity before
                    # the host exists. Keep that established identity check,
                    # then isolate the host-created Governance/Control Plane so
                    # a durable owner global-kill cannot contaminate release
                    # evidence and the smoke cannot mutate that durable ledger.
                    paths_module = imported_paths
                    original_private_control_plane_runtime_dir = (
                        imported_paths.private_control_plane_runtime_dir
                    )
                    control_plane_runtime = (
                        data_root / "runtime" / "control-plane-smoke-v1"
                    )
                    imported_paths.private_control_plane_runtime_dir = lambda: (
                        control_plane_runtime
                    )
                    from core import governance_nucleus_v1 as imported_governance

                    governance_module = imported_governance
                    original_governance_native_vault = imported_governance.native_vault
                    imported_governance.native_vault = (
                        _DiagnosticGovernanceVaultModuleV1(
                            original_governance_native_vault
                        )
                    )
                    from core import control_plane as imported_control_plane

                    control_plane_module = imported_control_plane
                    original_control_plane_runtime_dir = (
                        imported_control_plane.private_control_plane_runtime_dir
                    )
                    imported_control_plane.private_control_plane_runtime_dir = lambda: (
                        control_plane_runtime
                    )
                elif portable_current:
                    from core.onyx_portable_current_activation_v1 import (
                        PortableCurrentActivationV1Error,
                        prove_negative_boundary_v1,
                    )

                    phase11_runtime = data_root / "runtime" / "phase11-authority-v1"
                    original_runtime_dir = imported_main.runtime_dir
                    imported_main.runtime_dir = lambda: phase11_runtime
                    try:
                        prove_negative_boundary_v1()
                        raise NativeStartupSmokeError(
                            "portable-current negative proof returned"
                        )
                    except PortableCurrentActivationV1Error as exc:
                        reason = str(exc)
                        expected_reason = str(activation_contract["limitation_reason"])
                        if reason != expected_reason:
                            raise
                        payload = {
                            "activation": activation,
                            "activation_contract": activation_contract,
                            "activation_profile": activation_contract[
                                "activation_profile"
                            ],
                            "callbacks_bound": False,
                            "capability_limited": True,
                            "contract": NATIVE_STARTUP_SMOKE_CONTRACT,
                            "declared_activation": "v19",
                            "evidence_scope": (PORTABLE_CURRENT_NEGATIVE_BOUNDARY_GATE),
                            "host_constructed": False,
                            "interception": calls.evidence(),
                            "limitation_reason": reason,
                            "highest_proven_activation": ("v16_descriptor_ledger"),
                            "boundary_reached": "pre_v10",
                            "next_unimplemented_activation": (
                                "v4_portable_owner_authority"
                            ),
                            "native_evidence_required": True,
                            "network_calls": calls.network,
                            "process_calls": calls.process,
                            "provider_calls": calls.provider,
                            "secure_backend_probe_calls": (calls.secure_backend_probe),
                            "real_ui": False,
                            "safe_unavailability": True,
                            "status": "passed_limited",
                            "system": system,
                            TERMINAL_FENCE_EVIDENCE_KEY: terminal_fence,
                            "ui_renderer": "not_started_fail_closed",
                            "v15_v19_parity": False,
                            "window_visible": False,
                        }
                        if any((calls.network, calls.provider, calls.process)):
                            raise NativeStartupSmokeError(
                                "limited native startup crossed the provider-free boundary"
                            )
                        _write_result(output, payload)
                        return payload
                else:
                    from core.onyx_live_activation_v8 import activate_main

                    controller = activate_main(imported_main)

                ui = imported_main.OnyxUI("face.png")
                app = getattr(ui, "_app", None)
                if app is not None:
                    app.processEvents()
                instance = (
                    controller.instantiate_live(ui)
                    if system == "Windows" or portable_current
                    else imported_main.OnyxLive(ui)
                )
                if app is not None:
                    app.processEvents()
                window = getattr(ui, "_win", None)
                real_ui = type(ui).__name__ == "OnyxUI" and window is not None
                window_visible = bool(window is not None and window.isVisible())
                host_constructed = (
                    _authenticated_windows_v24_host_v1(
                        controller,
                        instance,
                        imported_main,
                    )
                    if system == "Windows"
                    else type(instance) is imported_main.OnyxLive
                )
                callbacks_bound = all(
                    callable(getattr(ui, name, None))
                    for name in (
                        "on_text_command",
                        "on_remote_clicked",
                        "on_interrupt",
                    )
                )
                if not all(
                    (real_ui, window_visible, host_constructed, callbacks_bound)
                ):
                    raise NativeStartupSmokeError(
                        "real native UI/host callback contract was not reached"
                    )
                renderer = (
                    "cinematic-v5"
                    if getattr(window, "_hud_v5_live", False) is True
                    else "safe-software-fallback"
                )
                payload: dict[str, object] = {
                    "activation": activation,
                    "activation_contract": activation_contract,
                    "activation_profile": activation_contract["activation_profile"],
                    "callbacks_bound": callbacks_bound,
                    "capability_limited": activation_contract["capability_limited"],
                    "contract": NATIVE_STARTUP_SMOKE_CONTRACT,
                    "host_constructed": host_constructed,
                    "interception": calls.evidence(),
                    "network_calls": calls.network,
                    "process_calls": calls.process,
                    "provider_calls": calls.provider,
                    "secure_backend_probe_calls": calls.secure_backend_probe,
                    "real_ui": real_ui,
                    "status": "passed",
                    "system": system,
                    TERMINAL_FENCE_EVIDENCE_KEY: terminal_fence,
                    "ui_renderer": renderer,
                    "window_visible": window_visible,
                }
                if any((calls.network, calls.provider, calls.process)):
                    raise NativeStartupSmokeError(
                        "native startup crossed the provider-free boundary"
                    )
                _write_result(output, payload)
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
                    paths_module=paths_module,
                    original_private_control_plane_runtime_dir=(
                        original_private_control_plane_runtime_dir
                    ),
                    governance_module=governance_module,
                    original_governance_native_vault=original_governance_native_vault,
                    control_plane_module=control_plane_module,
                    original_control_plane_runtime_dir=(
                        original_control_plane_runtime_dir
                    ),
                )
                if workspace_boundary is not None:
                    close_workspace = getattr(workspace_boundary, "close", None)
                    if callable(close_workspace):
                        try:
                            close_workspace()
                        except BaseException as exc:
                            cleanup_failures += (
                                f"workspace.boundary.close:{type(exc).__name__}",
                            )
                if data_boundary is not None:
                    close_data = getattr(data_boundary, "close", None)
                    if callable(close_data):
                        try:
                            close_data()
                        except BaseException as exc:
                            cleanup_failures += (
                                f"data.boundary.close:{type(exc).__name__}",
                            )
                if cleanup_failures:
                    detail = ",".join(cleanup_failures)
                    if active_error is not None:
                        active_error.add_note(
                            f"native startup cleanup failures: {detail}"
                        )
                    else:
                        raise NativeStartupSmokeError(
                            f"native startup cleanup failed: {detail}"
                        )


def run_native_startup_smoke_v1() -> dict[str, object]:
    raw_output = os.environ.get(NATIVE_STARTUP_SMOKE_OUTPUT_ENV, "").strip()
    if not raw_output:
        raise NativeStartupSmokeError("native startup smoke output is required")
    output = _lexical_absolute_output(raw_output)
    original_environment = dict(os.environ)
    try:
        return _run_host(output)
    except BaseException as exc:
        _write_result(
            output,
            {
                "contract": NATIVE_STARTUP_SMOKE_CONTRACT,
                "error": type(exc).__name__,
                "interception_scope": INTERCEPTION_SCOPE,
                "status": "failed",
                "system": platform.system(),
                TERMINAL_FENCE_EVIDENCE_KEY: False,
            },
        )
        raise
    finally:
        os.environ.clear()
        os.environ.update(original_environment)


def run_terminal_native_startup_smoke_v1() -> dict[str, object]:
    """Run release evidence with seams retained until this process exits."""

    if sys.argv[1:] != [NATIVE_STARTUP_SMOKE_ARGUMENT] or not bool(
        getattr(sys, "frozen", False) or getattr(sys, "_MEIPASS", None)
    ):
        raise NativeStartupSmokeError(
            "terminal native startup smoke requires the exact frozen CLI path"
        )
    raw_output = os.environ.get(NATIVE_STARTUP_SMOKE_OUTPUT_ENV, "").strip()
    if not raw_output:
        raise NativeStartupSmokeError("native startup smoke output is required")
    output = _lexical_absolute_output(raw_output)
    try:
        return _run_host(output, terminal_fence=True)
    except BaseException as exc:
        _write_result(
            output,
            {
                "contract": NATIVE_STARTUP_SMOKE_CONTRACT,
                "error": type(exc).__name__,
                "interception_scope": INTERCEPTION_SCOPE,
                "status": "failed",
                "system": platform.system(),
                TERMINAL_FENCE_EVIDENCE_KEY: True,
            },
        )
        raise


__all__ = [
    "ExternalCallCountersV1",
    "INTERCEPTION_SCOPE",
    "NATIVE_STARTUP_SMOKE_ARGUMENT",
    "NATIVE_STARTUP_SMOKE_CONTRACT",
    "NATIVE_STARTUP_SMOKE_OUTPUT_ENV",
    "PORTABLE_CURRENT_NEGATIVE_BOUNDARY_GATE",
    "TERMINAL_FENCE_EVIDENCE_KEY",
    "NativeStartupSmokeError",
    "external_call_boundary_v1",
    "run_native_startup_smoke_v1",
    "run_terminal_native_startup_smoke_v1",
]
