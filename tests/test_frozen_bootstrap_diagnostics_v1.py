from __future__ import annotations

import runpy
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "scripts/bootstrap_onyx.pyw"


def _namespace() -> dict[str, object]:
    return runpy.run_path(str(BOOTSTRAP), run_name="onyx_bootstrap_diagnostic_contract")


def test_only_bounded_diagnostic_arguments_receive_noninteractive_failure_handling() -> None:
    namespace = _namespace()
    check = namespace["_is_diagnostic_invocation"]
    assert check(["--preflight-only"])
    assert check(["--native-startup-smoke-test"])
    assert check(["--package-smoke-test"])
    assert check(["--installer-shutdown", "--timeout", "1"])
    assert not check([])
    assert not check(["--governance-smoke-test"])
    assert not check(["--native-startup-smoke-test", "extra"])


def test_windowed_source_native_diagnostic_returns_bounded_nonzero_and_logs(
    tmp_path: Path,
) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    core = tmp_path / "core"
    core.mkdir()
    (core / "__init__.py").write_text("", encoding="utf-8")
    (core / "paths.py").write_text(
        "from pathlib import Path\n"
        f"ROOT = Path({str(tmp_path)!r})\n"
        "def ensure_data_layout():\n"
        "    (ROOT / 'runtime/logs').mkdir(parents=True, exist_ok=True)\n"
        "def runtime_dir():\n"
        "    return ROOT / 'runtime'\n",
        encoding="utf-8",
    )
    shutil.copy2(BOOTSTRAP, scripts / "bootstrap_onyx.pyw")
    (scripts / "bootstrap_onyx_live_v24.pyw").write_text(
        "raise LookupError('bounded native diagnostic failure')\n",
        encoding="utf-8",
    )
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    executable = pythonw if pythonw.is_file() else Path(sys.executable)

    completed = subprocess.run(
        [str(executable), str(scripts / "bootstrap_onyx.pyw"),
         "--native-startup-smoke-test"],
        cwd=tmp_path,
        env={**__import__("os").environ, "PYTHONPATH": str(tmp_path)},
        timeout=30,
        check=False,
    )

    assert completed.returncode == 70
    log = tmp_path / "runtime/logs/onyx-bootstrap-diagnostic.log"
    rendered = log.read_text(encoding="utf-8")
    assert "LookupError: bounded native diagnostic failure" in rendered
    assert "Traceback (most recent call last)" in rendered


def test_windowed_package_diagnostic_converts_system_exit_to_70_and_logs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = _namespace()
    globals_ = namespace["_run_entrypoint"].__globals__
    monkeypatch.setattr(globals_["sys"], "argv", [str(BOOTSTRAP), "--package-smoke-test"])
    monkeypatch.setitem(globals_, "run", lambda: (_ for _ in ()).throw(
        SystemExit("packaged asset drift")
    ))
    seen: list[str] = []
    globals_["_write_diagnostic_traceback"] = lambda: seen.append("logged")

    with pytest.raises(SystemExit) as raised:
        namespace["_run_entrypoint"]()

    assert raised.value.code == 70
    assert seen == ["logged"]


def test_clean_diagnostic_system_exit_remains_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = _namespace()
    globals_ = namespace["_run_entrypoint"].__globals__
    monkeypatch.setattr(
        globals_["sys"], "argv", [str(BOOTSTRAP), "--capabilities-smoke-v1"]
    )
    monkeypatch.setitem(
        globals_, "run", lambda: (_ for _ in ()).throw(SystemExit(0))
    )
    globals_["_write_diagnostic_traceback"] = lambda: (_ for _ in ()).throw(
        AssertionError("successful diagnostics must not be logged as failures")
    )

    with pytest.raises(SystemExit) as raised:
        namespace["_run_entrypoint"]()

    assert raised.value.code == 0


@pytest.mark.parametrize("failure", (KeyboardInterrupt(), GeneratorExit()))
def test_diagnostic_entrypoint_never_swallows_process_interrupts(
    failure: BaseException,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = _namespace()
    globals_ = namespace["_run_entrypoint"].__globals__
    monkeypatch.setattr(globals_["sys"], "argv", [str(BOOTSTRAP), "--native-startup-smoke-test"])
    monkeypatch.setitem(globals_, "run", lambda: (_ for _ in ()).throw(failure))
    globals_["_write_diagnostic_traceback"] = lambda: (_ for _ in ()).throw(
        AssertionError("interrupt must not be logged as a diagnostic failure")
    )

    with pytest.raises(type(failure)):
        namespace["_run_entrypoint"]()


def test_installer_protocol_system_exit_is_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = _namespace()
    globals_ = namespace["_run_entrypoint"].__globals__
    monkeypatch.setattr(
        globals_["sys"], "argv",
        [str(BOOTSTRAP), "--installer-shutdown", "--timeout", "1"],
    )
    monkeypatch.setitem(
        globals_, "run", lambda: (_ for _ in ()).throw(SystemExit(9))
    )

    with pytest.raises(SystemExit) as raised:
        namespace["_run_entrypoint"]()

    assert raised.value.code == 9
