import json
import subprocess
from types import SimpleNamespace

import pytest

from scripts import successor_test_runner_v1 as module


@pytest.mark.parametrize("exit_code", [0, 1])
def test_success_and_failure_execute_once_even_across_claims(tmp_path, monkeypatch, exit_code):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert json.loads(kwargs["env"][module.STACK_ENV])[-1] == ["tests/a.py"]
        return SimpleNamespace(returncode=exit_code, stdout="result", stderr="detail")

    monkeypatch.setattr(module.subprocess, "run", run)
    monkeypatch.delenv(module.STACK_ENV, raising=False)
    runner = module.SuccessorTestRunner(tmp_path)
    for claim in ("one", "two"):
        if exit_code:
            with pytest.raises(AssertionError, match="resultdetail"):
                runner.run(claim, ("tests/a.py",))
        else:
            runner.run(claim, ("tests/a.py",))
    assert len(calls) == 1


def test_a_new_process_runner_does_not_inherit_passes(tmp_path, monkeypatch):
    calls = []
    monkeypatch.delenv(module.STACK_ENV, raising=False)

    def run(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0 if len(calls) == 1 else 1, stdout="changed", stderr="")

    monkeypatch.setattr(module.subprocess, "run", run)
    module.SuccessorTestRunner(tmp_path).run("first", ("tests/a.py",))
    with pytest.raises(AssertionError, match="changed"):
        module.SuccessorTestRunner(tmp_path).run("second", ("tests/a.py",))


@pytest.mark.parametrize("stack", ['[["tests/a.py"]]', '{}', 'invalid'])
def test_cycle_and_invalid_stack_fail_without_spawn(tmp_path, monkeypatch, stack):
    monkeypatch.setenv(module.STACK_ENV, stack)
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **k: pytest.fail("must not spawn"))
    with pytest.raises(AssertionError, match="cycle|invalid"):
        module.SuccessorTestRunner(tmp_path).run("one", ("tests/a.py",))


def test_timeout_is_not_retried(tmp_path, monkeypatch):
    calls = []
    monkeypatch.delenv(module.STACK_ENV, raising=False)

    def run(*args, **kwargs):
        calls.append(args)
        raise subprocess.TimeoutExpired("pytest", 900)

    monkeypatch.setattr(module.subprocess, "run", run)
    runner = module.SuccessorTestRunner(tmp_path)
    for _ in range(2):
        with pytest.raises(AssertionError, match="900 seconds"):
            runner.run("one", ("tests/a.py",))
    assert len(calls) == 1


@pytest.mark.parametrize("timeout", [0, -1, True, 901, float("inf"), "900"])
def test_budget_cannot_become_unbounded(tmp_path, timeout):
    with pytest.raises(ValueError, match="1..900"):
        module.SuccessorTestRunner(tmp_path, timeout=timeout)


def test_recursive_diagnostics_are_bounded_without_hiding_failure(tmp_path, monkeypatch):
    monkeypatch.delenv(module.STACK_ENV, raising=False)
    output = "original failure\n" + "detail" * 100000 + "\nfinal failure summary"
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=1, stdout=output, stderr=""))
    runner = module.SuccessorTestRunner(tmp_path)
    with pytest.raises(AssertionError) as captured:
        runner.run("bounded", ("tests/a.py",))
    message = str(captured.value)
    assert "original failure" in message
    assert message.endswith("final failure summary")
    assert "diagnostic characters]" in message
    assert len(message) < module.MAX_FAILURE_OUTPUT_CHARS + 200
    assert runner.results[("tests/a.py",)][0] == 1
