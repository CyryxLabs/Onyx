"""Execute each successor suite once, retaining failures rather than rerunning.

This is process-local pytest orchestration, never runtime evidence. Callers must
authenticate their bindings on each use. Cycles fail visibly instead of spawning
unbounded pytest trees; a bounded subprocess excerpt remains attached to failures.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

STACK_ENV = "ONYX_TEST_SUCCESSOR_STACK_V1"
MAX_FAILURE_OUTPUT_CHARS = 12000


def _failure_excerpt(output: str) -> str:
    # Recursive pytest failures otherwise repeat entire predecessor reports at
    # every level, producing multi-megabyte assertion messages. Never change the
    # exit status; retain the start and final summary and label omitted content.
    if len(output) <= MAX_FAILURE_OUTPUT_CHARS:
        return output
    half = MAX_FAILURE_OUTPUT_CHARS // 2
    return (output[:half] + f"\n[omitted {len(output) - 2 * half} diagnostic characters]\n"
            + output[-half:])


class SuccessorTestRunner:
    def __init__(self, root: Path, *, timeout: int = 900):
        if type(timeout) is not int or not 1 <= timeout <= 900:
            raise ValueError("successor timeout must be within 1..900 seconds")
        self.root = Path(root).resolve(strict=True)
        self.timeout = timeout
        self.results = {}

    def run(self, claim_id: str, paths: tuple[str, ...]) -> None:
        key = tuple(paths)
        if not key:
            raise AssertionError("successor test selection must not be empty")
        if key not in self.results:
            try:
                stack = json.loads(os.environ.get(STACK_ENV, "[]"))
            except (ValueError, TypeError) as exc:
                raise AssertionError("invalid successor test stack") from exc
            if type(stack) is not list or any(
                type(entry) is not list or any(type(path) is not str for path in entry)
                for entry in stack
            ):
                raise AssertionError("invalid successor test stack")
            if list(key) in stack:
                raise AssertionError(f"successor test cycle detected: {key}")
            environ = dict(os.environ)
            environ[STACK_ENV] = json.dumps([*stack, list(key)])
            with tempfile.TemporaryDirectory(prefix="onyx-successor-suite-") as directory:
                try:
                    result = subprocess.run(
                        [sys.executable, "-m", "pytest", "-q", "--tb=short",
                         "-p", "no:cacheprovider", *key, "--basetemp", directory],
                        cwd=self.root, capture_output=True, text=True, timeout=self.timeout,
                        check=False, env=environ,
                    )
                    outcome = (result.returncode, _failure_excerpt(result.stdout + result.stderr))
                except subprocess.TimeoutExpired:
                    outcome = (1, f"successor suite exceeded {self.timeout} seconds")
                self.results[key] = outcome
        code, output = self.results[key]
        if code != 0:
            raise AssertionError(f"current successor suite failed for {claim_id}:\n{output}")
