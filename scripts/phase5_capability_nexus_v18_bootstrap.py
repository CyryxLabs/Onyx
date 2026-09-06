"""Fixed private bootstrap used to close the Windows Job assignment race."""

from __future__ import annotations

import json
import os
import subprocess
import sys


_COMMAND_ENV = "ONYX_P53_V18_BOOTSTRAP_COMMAND"
_MODE_ENV = "ONYX_P53_V18_BOOTSTRAP_STDOUT_MODE"
_CONTRACT_ENV = "ONYX_P53_V18_BOOTSTRAP_CONTRACT"
_CONTRACT = "Phase53CapabilityNexusBootstrap.v18"


def _command() -> tuple[list[str], str]:
    raw = os.environ.get(_COMMAND_ENV, "")
    mode = os.environ.get(_MODE_ENV, "")
    if os.environ.get(_CONTRACT_ENV) != _CONTRACT or mode not in {"pipe", "devnull"}:
        raise RuntimeError("bootstrap private contract is invalid")
    try:
        command = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("bootstrap command envelope is invalid") from exc
    if (
        not isinstance(command, list)
        or not command
        or len(command) > 128
        or any(not isinstance(item, str) or not item or len(item) > 8192 for item in command)
        or raw != json.dumps(command, ensure_ascii=True, separators=(",", ":"))
    ):
        raise RuntimeError("bootstrap command envelope is noncanonical")
    return command, mode


def main() -> int:
    if sys.argv != [sys.argv[0]]:
        raise RuntimeError("bootstrap exposes no command-line surface")
    command, mode = _command()
    if sys.stdin.readline() != "GO\n" or sys.stdin.read(1) != "":
        raise RuntimeError("bootstrap GO barrier is invalid")
    child_env = os.environ.copy()
    for key in (_COMMAND_ENV, _MODE_ENV, _CONTRACT_ENV):
        child_env.pop(key, None)
    stdout_target = subprocess.PIPE if mode == "pipe" else subprocess.DEVNULL
    process = subprocess.Popen(
        command,
        env=child_env,
        text=True,
        stdout=stdout_target,
        stderr=subprocess.PIPE,
        shell=False,
    )
    stdout, stderr = process.communicate()
    if stdout:
        sys.stdout.write(stdout)
        sys.stdout.flush()
    if stderr:
        sys.stderr.write(stderr)
        sys.stderr.flush()
    return int(process.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
