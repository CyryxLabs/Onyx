from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from core import installer_lifecycle_v1 as lifecycle


ROOT = Path(__file__).resolve().parents[1]


def _record(*, pid: int, started: str, executable: Path) -> dict[str, object]:
    return {
        "schema": lifecycle.SCHEMA,
        "state": "listening",
        "generation": "a" * 32,
        "pipe": r"\\.\pipe\CyryxLabs-Onyx-" + "a" * 32,
        "pid": pid,
        "started": started,
        "executable": str(executable),
        "executable_sha256": lifecycle._sha256_file(executable),
        "version": "1.1.9-test",
        "issued_at_ns": 1,
    }


def test_bootstrap_handles_installer_client_before_activation() -> None:
    source = (ROOT / "scripts" / "bootstrap_onyx.pyw").read_text(encoding="utf-8")
    control = source.index('sys.argv[1] == "--installer-shutdown"')
    activation = source.index("runpy.run_path(str(_selected_bootstrap())")
    assert control < activation
    assert "installer_client_main(sys.argv[2:])" in source
    assert "runpy.run_path" not in source[control:activation]
    root_assignment = source.index("ROOT = Path(")
    root_promotion = source.index("sys.path.insert(0, str(ROOT))")
    assert root_assignment < root_promotion < control
    assert "sys.path[:] = [" in source[root_assignment:control]


def test_inno_uses_cooperative_channel_and_never_silently_kills() -> None:
    source = (ROOT / "packaging" / "windows" / "onyx.iss").read_text(encoding="utf-8")
    assert "CloseApplications=no" in source
    assert "function PrepareToInstall" in source
    assert "function InitializeUninstall" in source
    assert "--installer-shutdown" in source
    assert "ewWaitUntilTerminated" in source
    assert "ResultCode <> 0" in source
    assert "GetNamedOnyxProcessState" in source
    assert "CheckForMutexes('Local\\CyryxLabs.Onyx.Live.V15')" in source
    assert "process inventory could not be verified" in source
    assert "SuppressibleMsgBox(" in source
    assert "    MsgBox(" not in source
    assert "taskkill" not in source.casefold()
    assert "TerminateProcess" not in source


def test_inno_smoke_lifecycle_override_preserves_production_default() -> None:
    source = (ROOT / "packaging" / "windows" / "onyx.iss").read_text(encoding="utf-8")
    assert (
        '#define LifecycleRecordOverride GetEnv("ONYX_LIFECYCLE_RECORD_PATH")' in source
    )
    assert '#if LifecycleRecordOverride != ""' in source
    assert "Result := '{#LifecycleRecordOverride}';" in source
    assert (
        "{localappdata}\\Cyryx Labs\\Onyx\\runtime\\installer-lifecycle-v1\\resident.json"
        in source
    )


def test_inno_blocks_legacy_resident_even_without_a_window() -> None:
    source = (ROOT / "packaging" / "windows" / "onyx.iss").read_text(encoding="utf-8")
    boundary = source[source.index("function RefuseUnknownOrLegacyResident") :]
    boundary = boundary[: boundary.index("function RequestCooperativeOnyxShutdown")]
    assert "ProcessState = 1" in boundary
    assert "StableOnyxMutexPresent()" in boundary
    assert "LegacyOnyxWindowPresent()" in boundary
    assert " or " in boundary


def test_windows_frozen_spec_contains_named_pipe_runtime() -> None:
    source = (ROOT / "packaging" / "onyx.spec").read_text(encoding="utf-8")
    for module in ("win32con", "win32file", "win32pipe", "win32security"):
        assert f'"{module}"' in source


def test_record_round_trip_is_exact_and_atomic(tmp_path: Path) -> None:
    root = lifecycle._ensure_private_root(
        tmp_path / "installer-lifecycle-v1", enforce_security=False
    )
    expected = _record(
        pid=os.getpid(),
        started=lifecycle._process_started(os.getpid()),
        executable=Path(sys.executable).resolve(),
    )
    lifecycle._atomic_write(root, lifecycle.RECORD_NAME, expected)
    assert lifecycle._read_record(root) == expected
    assert "token" not in expected
    assert not list(root.glob("*.tmp"))


@pytest.mark.skipif(os.name != "nt", reason="Windows missing-file attributes contract")
def test_missing_record_is_clean_not_running(tmp_path: Path) -> None:
    root = lifecycle._ensure_private_root(
        tmp_path / "installer-lifecycle-v1", enforce_security=False
    )
    result = lifecycle.request_installer_shutdown(
        reason="upgrade",
        root=root,
        executable=Path(sys.executable),
        enforce_security=False,
    )
    assert result == lifecycle.ClientResult(
        lifecycle.EXIT_OK,
        "not-running",
        "no resident lifecycle record",
    )


def test_record_symlink_is_rejected(tmp_path: Path) -> None:
    root = lifecycle._ensure_private_root(
        tmp_path / "installer-lifecycle-v1", enforce_security=False
    )
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    try:
        (root / lifecycle.RECORD_NAME).symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable on this Windows host")
    with pytest.raises(lifecycle.InstallerLifecycleSecurityError):
        lifecycle._read_record(root)


@pytest.mark.skipif(os.name != "nt", reason="Windows process identity contract")
def test_stale_record_is_removed_without_starting_runtime(tmp_path: Path) -> None:
    root = lifecycle._ensure_private_root(
        tmp_path / "installer-lifecycle-v1", enforce_security=False
    )
    stale = _record(
        pid=2_000_000_000,
        started="1.000000",
        executable=Path(sys.executable).resolve(),
    )
    lifecycle._atomic_write(root, lifecycle.RECORD_NAME, stale)
    result = lifecycle.request_installer_shutdown(
        reason="upgrade",
        root=root,
        executable=Path(sys.executable),
        enforce_security=False,
    )
    assert result.exit_code == lifecycle.EXIT_OK
    assert result.status == "not-running"
    assert not (root / lifecycle.RECORD_NAME).exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows ACL contract")
def test_private_root_has_one_current_user_ace(tmp_path: Path) -> None:
    import win32security

    root = lifecycle._ensure_private_root(
        tmp_path / "installer-lifecycle-v1", enforce_security=True
    )
    security = win32security.GetNamedSecurityInfo(
        str(root),
        win32security.SE_FILE_OBJECT,
        win32security.OWNER_SECURITY_INFORMATION
        | win32security.DACL_SECURITY_INFORMATION,
    )
    assert security.GetSecurityDescriptorOwner() == lifecycle._current_windows_sid()
    assert security.GetSecurityDescriptorDacl().GetAceCount() == 1


def _start_server(tmp_path: Path, mode: str) -> tuple[subprocess.Popen, Path]:
    private = tmp_path / "installer-lifecycle-v1"
    helper = tmp_path / "lifecycle_server.py"
    helper.write_text(
        """
import os
import sys
import threading
import time
from pathlib import Path
from core.installer_lifecycle_v1 import (
    InstallerLifecycleServer,
    _process_executable,
)

root = Path(sys.argv[1])
mode = sys.argv[2]
state = {"value": "refused" if mode == "refuse" else "pending"}

def begin(_reason):
    if mode == "refuse":
        return False
    state["value"] = "complete"
    return True

def status():
    detail = (
        "test startup boundary refused"
        if state["value"] == "refused"
        else "test cleanup complete"
    )
    return (state["value"], detail)

def exit_after():
    timer = threading.Timer(0.15, lambda: os._exit(0))
    timer.daemon = True
    timer.start()
    return True

server = InstallerLifecycleServer(
    begin_shutdown=begin,
    shutdown_status=status,
    exit_after_receipt=exit_after,
    version="1.1.9-test",
    root=root,
    executable=_process_executable(os.getpid()),
    cleanup_timeout=3.0,
    enforce_security=False,
)
server.start()
while True:
    time.sleep(0.1)
""",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = (
        str(ROOT) + os.pathsep + environment.get("PYTHONPATH", "")
    )
    process = subprocess.Popen(
        [sys.executable, str(helper), str(private), mode],
        cwd=ROOT,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if (private / lifecycle.RECORD_NAME).exists():
            return process, private
        if process.poll() is not None:
            raise AssertionError(process.stderr.read())
        time.sleep(0.05)
    process.terminate()
    raise AssertionError("lifecycle server did not publish its record")


@pytest.mark.skipif(os.name != "nt", reason="Windows named-pipe integration")
def test_subprocess_cleanup_receipt_and_exact_process_exit(tmp_path: Path) -> None:
    process, private = _start_server(tmp_path, "complete")
    try:
        resident = lifecycle._read_record(private)
        assert resident is not None
        executable = lifecycle._process_executable(os.getpid())
        result = lifecycle.request_installer_shutdown(
            reason="upgrade",
            timeout=10.0,
            root=private,
            executable=executable,
            enforce_security=False,
        )
        assert result.exit_code == lifecycle.EXIT_OK
        assert result.status == "complete"
        assert result.receipt is not None
        assert int(result.receipt["server"]["pid"]) == int(resident["pid"])
        assert process.wait(timeout=2) == 0
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)


@pytest.mark.skipif(os.name != "nt", reason="Windows named-pipe integration")
def test_stale_record_generation_grants_no_shutdown_authority(tmp_path: Path) -> None:
    process, private = _start_server(tmp_path, "complete")
    try:
        record = lifecycle._read_record(private)
        assert record is not None
        record["generation"] = "0" * 32
        lifecycle._atomic_write(private, lifecycle.RECORD_NAME, record)
        result = lifecycle.request_installer_shutdown(
            reason="upgrade",
            timeout=3.0,
            root=private,
            executable=lifecycle._process_executable(os.getpid()),
            enforce_security=False,
        )
        assert result.exit_code in {lifecycle.EXIT_PROTOCOL, lifecycle.EXIT_SECURITY}
        assert process.poll() is None
    finally:
        process.terminate()
        process.wait(timeout=5)


@pytest.mark.skipif(os.name != "nt", reason="Windows named-pipe peer identity")
def test_named_pipe_rejects_actual_wrong_peer_before_challenge(tmp_path: Path) -> None:
    process, private = _start_server(tmp_path, "complete")
    try:
        record = lifecycle._read_record(private)
        assert record is not None
        pipe_leaf = str(record["pipe"]).rsplit("\\", 1)[-1]
        script = (
            "$p=[IO.Pipes.NamedPipeClientStream]::new('.', $args[0], "
            "[IO.Pipes.PipeDirection]::InOut);"
            "$p.Connect(3000);$b=New-Object byte[] 4;"
            "try{$n=$p.Read($b,0,4)}catch{$n=0};$p.Dispose();"
            "if($n -eq 0){exit 0}else{exit 9}"
        )
        wrong = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                script,
                pipe_leaf,
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert wrong.returncode == 0, (wrong.stdout, wrong.stderr)
        assert process.poll() is None
    finally:
        process.terminate()
        process.wait(timeout=5)


@pytest.mark.skipif(os.name != "nt", reason="Windows client executable identity")
def test_wrong_client_executable_path_is_refused_before_connect(tmp_path: Path) -> None:
    process, private = _start_server(tmp_path, "complete")
    impostor = tmp_path / "Onyx.exe"
    impostor.write_bytes(Path(sys.executable).read_bytes())
    try:
        result = lifecycle.request_installer_shutdown(
            reason="upgrade",
            timeout=2.0,
            root=private,
            executable=impostor,
            enforce_security=False,
        )
        assert result.exit_code == lifecycle.EXIT_SECURITY
        assert "path does not match" in result.detail
        assert process.poll() is None
    finally:
        process.terminate()
        process.wait(timeout=5)


@pytest.mark.skipif(os.name != "nt", reason="Windows named-pipe integration")
def test_consumed_request_cannot_be_replayed(tmp_path: Path) -> None:
    process, private = _start_server(tmp_path, "refuse")
    try:
        old = lifecycle._read_record(private)
        assert old is not None
        first = lifecycle.request_installer_shutdown(
            reason="upgrade",
            timeout=3.0,
            root=private,
            executable=lifecycle._process_executable(os.getpid()),
            enforce_security=False,
        )
        assert first.exit_code == lifecycle.EXIT_REFUSED
        assert first.detail == "test startup boundary refused"
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                current = lifecycle._read_record(private)
            except lifecycle.InstallerLifecycleSecurityError:
                time.sleep(0.05)
                continue
            if current is not None and current["generation"] != old["generation"]:
                break
            time.sleep(0.05)
        lifecycle._atomic_write(private, lifecycle.RECORD_NAME, old)
        replay = lifecycle.request_installer_shutdown(
            reason="upgrade",
            timeout=1.0,
            root=private,
            executable=lifecycle._process_executable(os.getpid()),
            enforce_security=False,
        )
        assert replay.exit_code == lifecycle.EXIT_PROTOCOL
        assert process.poll() is None
    finally:
        process.terminate()
        process.wait(timeout=5)
