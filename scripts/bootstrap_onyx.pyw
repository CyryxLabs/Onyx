"""Stable Onyx desktop bootstrap.

This entry point intentionally has no version in its filename. Desktop
shortcuts and installers should target it so activation upgrades do not leave
users on an older interface.
"""

from __future__ import annotations

import runpy
import os
import platform
import sys
import traceback
from pathlib import Path


# Runtime source bytes are shipped only as integrity inputs. Never let the
# frozen application turn those immutable inputs into writable cache trees.
sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])).resolve()
# The frozen/source root is the authority for all subsequent critical imports.
# Remove every older occurrence first so an injected cwd/PYTHONPATH copy of
# ``core`` can never win before the installer-control early path.
_root_key = os.path.normcase(os.path.abspath(os.fspath(ROOT)))
sys.path[:] = [
    entry
    for entry in sys.path
    if os.path.normcase(os.path.abspath(os.fspath(entry or os.curdir))) != _root_key
]
sys.path.insert(0, str(ROOT))
CURRENT_BOOTSTRAP = ROOT / "scripts" / "bootstrap_onyx_live_v24.pyw"
# V24 is the current Windows activation boundary over exact V23.
# Accepted predecessor assertion retained as evidence, not assignment:
# CURRENT_BOOTSTRAP = ROOT / "scripts" / "bootstrap_onyx_live_v20.pyw"
# CURRENT_BOOTSTRAP = ROOT / "scripts" / "bootstrap_onyx_live_v19.pyw"
PORTABLE_CURRENT_BOOTSTRAP = ROOT / "scripts" / "bootstrap_onyx_portable_current_v1.pyw"
PORTABLE_CURRENT_FLAG = "ONYX_PORTABLE_CURRENT_ACTIVATION_V1"
PORTABLE_CURRENT_SYSTEMS = frozenset({"Darwin", "Linux"})
DIAGNOSTIC_FAILURE_EXIT = 70
_DIAGNOSTIC_EXACT_ARGUMENTS = frozenset(
    {
        ("--preflight-only",),
        ("--native-startup-smoke-test",),
        ("--package-smoke-test",),
        ("--capabilities-smoke-v1",),
        ("--parity-smoke-v1",),
    }
)


def _normalize_windows_empty_launch_arguments() -> None:
    """Discard only empty argv entries emitted by Windows shell launchers.

    Some Windows shortcut/process APIs serialize an omitted optional argument
    as an explicit empty quoted value, producing ``Onyx.exe ""``.  That is
    operationally the same desktop launch as ``Onyx.exe``.  Normalizing only
    the exact empty string preserves every non-empty diagnostic and refusal
    boundary, including whitespace and unknown switches.
    """

    # Explorer normally decodes an empty shortcut parameter to ``""`` in
    # argv.  A legacy WScript/Inno shortcut can instead preserve the two quote
    # characters and PyInstaller then forwards them literally.  Both shapes
    # mean "no desktop arguments" only when they are the entire argument
    # vector; mixed vectors and every other non-empty value remain untouched.
    if platform.system() != "Windows" or sys.argv[1:] not in ([""], ['""']):
        return
    sys.argv[:] = [sys.argv[0]]


def _selected_bootstrap() -> Path:
    """Select the packaged host without depending on a launcher-owned env var.

    Frozen macOS/Linux applications use the current portable activation by
    default.  ``=1`` remains the explicit source/diagnostic opt-in, while
    ``=0`` is the explicit diagnostic predecessor override.  Windows always
    retains the V24 activation boundary.
    """

    if platform.system() not in PORTABLE_CURRENT_SYSTEMS:
        return CURRENT_BOOTSTRAP

    requested = os.environ.get(PORTABLE_CURRENT_FLAG)
    if requested not in (None, "0", "1"):
        raise RuntimeError("ONYX_PORTABLE_CURRENT_V1_SELECTION_INVALID")
    if requested == "1" or (requested is None and bool(getattr(sys, "frozen", False))):
        # The portable bootstrap authenticates this same value before it
        # prepares the canonical environment.  Set the internally selected
        # default here so desktop entries, launchd and systemd need no hidden
        # environment configuration.
        os.environ[PORTABLE_CURRENT_FLAG] = "1"
        return PORTABLE_CURRENT_BOOTSTRAP
    return CURRENT_BOOTSTRAP


def _preflight_package_smoke() -> None:
    """Exercise the selected packaged contract without starting the assistant."""

    selected = _selected_bootstrap()
    namespace = runpy.run_path(
        str(selected),
        run_name="onyx_stable_bootstrap_contract_for_package_smoke",
    )
    select_environment = namespace.get("_bootstrap_environment")
    if not callable(select_environment):
        raise RuntimeError("Onyx stable package-smoke contract is unavailable")
    if platform.system() != "Windows":
        result = select_environment(os.environ)
        if selected == PORTABLE_CURRENT_BOOTSTRAP:
            if type(result) is not dict or result.get(PORTABLE_CURRENT_FLAG) != "1":
                raise RuntimeError("Onyx portable package-smoke contract drifted")
            return
        mode, _prepared = result
        if mode != "v23":
            raise RuntimeError("Onyx POSIX predecessor package smoke drifted")
        return
    mode, prepared = select_environment(os.environ)
    if mode != "v24":
        raise RuntimeError("Onyx Windows package smoke did not select V24")

    # Preflight authenticates the complete V23 predecessor and the V24 host
    # contract. It deliberately does not install/start the runtime, connect a
    # provider, or launch a child process.
    import main as onyx_main
    from core.onyx_live_activation_v24 import preflight_host

    preflight_host(onyx_main, prepared)


def _is_diagnostic_invocation(arguments: list[str]) -> bool:
    values = tuple(arguments)
    return values in _DIAGNOSTIC_EXACT_ARGUMENTS or (
        bool(values) and values[0] == "--installer-shutdown"
    )


def _write_diagnostic_traceback() -> None:
    """Emit a diagnostic failure without importing Qt or opening a dialog."""

    rendered = traceback.format_exc()
    if sys.stderr is not None:
        try:
            sys.stderr.write(rendered)
            sys.stderr.flush()
        except (OSError, ValueError):
            pass
    try:
        from core.paths import ensure_data_layout, runtime_dir

        ensure_data_layout()
        log_path = runtime_dir() / "logs" / "onyx-bootstrap-diagnostic.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(rendered)
    except Exception:
        # stderr remains the primary bounded diagnostic surface.  A log is
        # best-effort only when the private owner data boundary is available.
        pass


def _should_convert_diagnostic_failure(
    arguments: list[str], failure: BaseException
) -> bool:
    """Limit windowless failure conversion to bounded diagnostic commands."""

    if isinstance(failure, (KeyboardInterrupt, GeneratorExit)):
        return False
    # ``raise SystemExit(main(...))`` is the normal CLI protocol. A zero/None
    # code is success and must remain zero even for a windowless diagnostic;
    # only non-zero diagnostic exits are converted to the bounded code 70.
    if isinstance(failure, SystemExit) and failure.code in (None, 0):
        return False
    # Installer shutdown is a control client.  Its explicit SystemExit code is
    # the protocol result and must remain observable by the installer.
    if arguments and arguments[0] == "--installer-shutdown":
        return not isinstance(failure, SystemExit)
    return _is_diagnostic_invocation(arguments)


def run() -> None:
    _normalize_windows_empty_launch_arguments()
    if sys.argv[1:] and sys.argv[1] == "--social":
        from scripts.onyx_social_cli import cli_main as social_main

        raise SystemExit(social_main(sys.argv[2:]))
    if sys.argv[1:] and sys.argv[1] == "--network-guardian":
        from core.network_guardian_v1 import main as guardian_main

        raise SystemExit(guardian_main(sys.argv[2:]))
    if sys.argv[1:] and sys.argv[1] == "--installer-shutdown":
        # This control path must run before any activation, Qt, microphone, or
        # Gemini import.  It is the cooperative client of the already-running
        # executable and never starts a second assistant runtime.
        from core.installer_lifecycle_v1 import installer_client_main

        raise SystemExit(installer_client_main(sys.argv[2:]))
    if sys.argv[1:] == ["--package-smoke-test"]:
        _preflight_package_smoke()
        from main import _run_package_smoke_test

        _run_package_smoke_test()
        return
    if getattr(sys, "frozen", False) and sys.argv[1:] == ["--capabilities-smoke-v1"]:
        from scripts.onyx_capabilities_cli import main as capabilities_main

        raise SystemExit(capabilities_main(["safe-test"]))
    if getattr(sys, "frozen", False) and sys.argv[1:] == ["--parity-smoke-v1"]:
        from scripts.onyx_parity_cli import main as parity_main

        raise SystemExit(parity_main(["--root", str(ROOT), "--packaged"]))
    try:
        runpy.run_path(str(_selected_bootstrap()), run_name="__main__")
    except RuntimeError as exc:
        from core.onyx_live_activation_v15 import (
            PLATFORM_REFUSAL_EXIT,
            PLATFORM_REFUSAL_SIGNAL,
        )

        if (
            getattr(sys, "frozen", False)
            and sys.argv[1:]
            in (
                ["--preflight-only"],
                ["--governance-smoke-test"],
                ["--founder-smoke-test"],
                ["--document-intake-smoke-test"],
                ["--dayops-smoke-test"],
                ["--advanced-operations-smoke-test"],
                ["--advanced-commands-smoke-test"],
                ["--native-startup-smoke-test"],
            )
            and str(exc) == PLATFORM_REFUSAL_SIGNAL
        ):
            if sys.stderr is not None:
                print(PLATFORM_REFUSAL_SIGNAL, file=sys.stderr, flush=True)
            os._exit(PLATFORM_REFUSAL_EXIT)
        raise
    if getattr(sys, "frozen", False) and sys.argv[1:] == ["--preflight-only"]:
        # Importing the complete host can leave optional library worker
        # threads alive after a successful diagnostic. The packaged preflight
        # must terminate deterministically without opening the UI.
        if sys.stdout is not None:
            sys.stdout.flush()
        if sys.stderr is not None:
            sys.stderr.flush()
        os._exit(0)


def _run_entrypoint() -> None:
    """Run the stable entry point with noninteractive diagnostic failures."""

    try:
        run()
    except BaseException as failure:
        if not _should_convert_diagnostic_failure(sys.argv[1:], failure):
            raise
        _write_diagnostic_traceback()
        raise SystemExit(DIAGNOSTIC_FAILURE_EXIT) from None


if __name__ == "__main__":
    _run_entrypoint()
